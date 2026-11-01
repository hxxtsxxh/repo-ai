"""Test discovery.

Answers three questions an agent needs before it writes a line of code:
  * where do tests live, and how are they organised?
  * which framework, so new tests match existing style?
  * what command runs them, so the agent can verify its own work?

The third is the one that changes outcomes. An agent that can run the suite
converges; one that cannot guesses.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .models import Dependency, FileRecord, TestSuite

FRAMEWORK_IMPORT_MARKERS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^\s*import\s+pytest|^\s*from\s+pytest\b|@pytest\.", re.M), "pytest", "Python"),
    # `from unittest import TestCase` too (more-itertools); `from unittest.mock import …` is not a unittest suite
    (re.compile(r"^\s*import\s+unittest\b(?!\.)|^\s*from\s+unittest\s+import\b|unittest\.TestCase", re.M), "unittest",
     "Python"),
    (re.compile(r"\bfrom\s+django\.test\b"), "Django test", "Python"),
    (re.compile(r"\bfrom\s+fastapi\.testclient\b"), "FastAPI TestClient", "Python"),
    (re.compile(r"\bfrom\s+hypothesis\b"), "Hypothesis", "Python"),
    (re.compile(r"""from\s+['"]vitest['"]|\bvi\.(mock|fn)\("""), "Vitest", "JS/TS"),
    (re.compile(r"\bjest\.(mock|fn|spyOn)\b|@jest/globals"), "Jest", "JS/TS"),
    (re.compile(r"""from\s+['"]@playwright/test['"]"""), "Playwright", "JS/TS"),
    (re.compile(r"\bcy\.(visit|get)\("), "Cypress", "JS/TS"),
    (re.compile(r"""\brequire\(['"]mocha['"]\)|\bdescribe\(.*function"""), "Mocha", "JS/TS"),
    (re.compile(r"@testing-library/"), "Testing Library", "JS/TS"),
    (re.compile(r"org\.junit\.jupiter"), "JUnit 5", "Java"),
    (re.compile(r"org\.junit\.(Test|Assert)"), "JUnit 4", "Java"),
    (re.compile(r"org\.testng"), "TestNG", "Java"),
    (re.compile(r"org\.mockito"), "Mockito", "Java"),
    (re.compile(r"@SpringBootTest|@WebMvcTest|@DataJpaTest"), "Spring Boot Test", "Java"),
    (re.compile(r"\bfunc\s+Test\w+\(t\s*\*testing\.T\)"), "go test", "Go"),
    (re.compile(r"github\.com/stretchr/testify"), "Testify", "Go"),
    (re.compile(r"#\[test\]|#\[tokio::test\]"), "Rust test", "Rust"),
    (re.compile(r"\bRSpec\.describe|\bdescribe\s+['\"]"), "RSpec", "Ruby"),
    (re.compile(r"Minitest::Test"), "Minitest", "Ruby"),
    (re.compile(r"PHPUnit\\\\Framework\\\\TestCase"), "PHPUnit", "PHP"),
    (re.compile(r"\[Fact\]|\[Theory\]|Xunit"), "xUnit", "C#"),
    (re.compile(r"\[TestMethod\]|MSTest"), "MSTest", "C#"),
    (re.compile(r"NUnit\.Framework"), "NUnit", "C#"),
]

E2E_TOKENS = ("e2e", "end-to-end", "endtoend", "acceptance", "cypress",
              "playwright", "selenium", "smoke", "browser", "ui-test")
INTEGRATION_TOKENS = ("integration", "it", "functional", "contract", "api-test",
                      "component-test", "system")

DEP_TEST_FRAMEWORKS = {
    "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha", "jasmine": "Jasmine",
    "@playwright/test": "Playwright", "playwright": "Playwright",
    "cypress": "Cypress", "pytest": "pytest", "junit:junit": "JUnit 4",
    "org.junit.jupiter:junit-jupiter": "JUnit 5", "org.testng:testng": "TestNG",
    "rspec": "RSpec", "phpunit/phpunit": "PHPUnit",
    "github.com/stretchr/testify": "Testify", "xunit": "xUnit", "nunit": "NUnit",
}

DEFAULT_COMMANDS = {
    "pytest": "pytest", "unittest": "python -m unittest discover",
    "Jest": "npm test", "Vitest": "npx vitest run", "Mocha": "npm test",
    "Playwright": "npx playwright test", "Cypress": "npx cypress run",
    "JUnit 5": "mvn test", "JUnit 4": "mvn test", "TestNG": "mvn test",
    "Spring Boot Test": "mvn test", "go test": "go test ./...",
    "Testify": "go test ./...", "Rust test": "cargo test",
    "RSpec": "bundle exec rspec", "Minitest": "bundle exec rake test",
    "PHPUnit": "vendor/bin/phpunit", "xUnit": "dotnet test",
    "NUnit": "dotnet test", "MSTest": "dotnet test",
}


_FAMILY_TOOLS = {
    "python": ("pytest", "python", "tox", "nox", "poetry", "uv", "hatch", "make"),
    "js": ("npm", "pnpm", "yarn", "bun", "npx", "jest", "vitest", "mocha", "playwright", "cypress"),
    "jvm": ("mvn", "./mvnw", "gradle", "./gradlew", "make"),
    "go": ("go", "make"), "rust": ("cargo", "make"), "ruby": ("bundle", "rake", "rspec", "make"),
    "php": ("composer", "vendor/bin/phpunit", "phpunit"), "dotnet": ("dotnet",),
}
_FAMILY_OF = {
    "pytest": "python", "unittest": "python", "Django test": "python",
    "FastAPI TestClient": "python", "Hypothesis": "python",
    "Vitest": "js", "Jest": "js", "Playwright": "js", "Cypress": "js", "Mocha": "js",
    "Testing Library": "js", "Jasmine": "js",
    "JUnit 5": "jvm", "JUnit 4": "jvm", "TestNG": "jvm", "Mockito": "jvm", "Spring Boot Test": "jvm",
    "go test": "go", "Testify": "go", "Rust test": "rust", "RSpec": "ruby", "Minitest": "ruby",
    "PHPUnit": "php", "xUnit": "dotnet", "MSTest": "dotnet", "NUnit": "dotnet",
}


def suite_command(root: str, framework: str, candidates: list[str]) -> str:
    """Pick the declared test command that actually runs this suite.

    Preference: a command scoped to an enclosing directory (`cd web && npm
    test` for `web/src/...`), then a root-level command from the same tool
    family (`make test` is not a Vitest runner), then the framework default.
    """
    best: tuple[int, str] | None = None
    for cmd in candidates:
        match = re.match(r"^cd (\S+) && ", cmd)
        if match:
            base = match.group(1).rstrip("/")
            if root == base or root.startswith(base + "/"):
                if best is None or len(base) > best[0]:
                    best = (len(base), cmd)
    if best:
        return best[1]
    tools = _FAMILY_TOOLS.get(_FAMILY_OF.get(framework, ""), ())
    root_level = [c for c in candidates if not c.startswith("cd ")]
    for cmd in root_level:
        head = cmd.split()[0] if cmd.split() else ""
        if head in tools and head != "make":
            return cmd
    if DEFAULT_COMMANDS.get(framework):
        # `make test` is only trusted when it is the sole option for the family.
        make = next((c for c in root_level if c.startswith("make") and "make" in tools), "")
        others = [c for c in candidates if c.startswith("cd ")]
        if make and not others:
            return make
        return DEFAULT_COMMANDS[framework]
    return root_level[0] if root_level else ""


def _kind_for(path: str) -> str:
    lower = path.lower()
    if any(tok in lower for tok in E2E_TOKENS):
        return "e2e"
    if any(re.search(rf"(^|[/._-]){re.escape(tok)}([/._-]|$)", lower) for tok in INTEGRATION_TOKENS):
        return "integration"
    return "unit"


def _suite_root(path: str) -> str:
    """The highest directory that still looks test-specific."""
    parts = PurePosixPath(path).parts[:-1]
    markers = {"test", "tests", "spec", "specs", "__tests__", "e2e", "it",
               "integration", "cypress", "playwright", "testing"}
    for idx, part in enumerate(parts):
        if part.lower() in markers:
            return "/".join(parts[: idx + 1])
    return "/".join(parts) if parts else "."


# A Python test file with top-level `def test_*` functions or base-less `class Test*`
# and no framework import is pytest style: unittest cannot collect either. A weak
# vote, used only when no framework import or declared test dependency decides.
_PYTEST_STYLE = re.compile(r"^(?:async\s+)?def\s+test\w*\s*\(|^class\s+Test\w*\s*(?::|\(\s*\)\s*:)", re.M)


def discover_test_suites(
    files: list[FileRecord],
    file_texts: dict[str, str],
    deps: list[Dependency],
    commands: dict[str, list[str]],
) -> list[TestSuite]:
    test_files = [f for f in files if f.role == "test"]
    if not test_files:
        return []
    paths = {f.path for f in files}

    dep_names = {d.name.lower() for d in deps}
    dep_frameworks = {
        label for name, label in DEP_TEST_FRAMEWORKS.items() if name.lower() in dep_names
    }

    grouped: dict[tuple[str, str], list[FileRecord]] = defaultdict(list)
    framework_votes: dict[tuple[str, str], Counter] = defaultdict(Counter)
    pytest_style: Counter = Counter()

    for record in test_files:
        root = _suite_root(record.path)
        kind = _kind_for(record.path)
        key = (root, kind)
        grouped[key].append(record)
        text = file_texts.get(record.path, "")
        if text:
            head = text[:8000]
            for pattern, label, _lang in FRAMEWORK_IMPORT_MARKERS:
                if pattern.search(head):
                    framework_votes[key][label] += 1
            if record.path.endswith(".py") and _PYTEST_STYLE.search(head):
                pytest_style[key] += 1

    suites: list[TestSuite] = []
    for (root, kind), records in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        votes = framework_votes.get((root, kind))
        if votes:
            framework = votes.most_common(1)[0][0]
        elif dep_frameworks:
            framework = sorted(dep_frameworks)[0]
        elif pytest_style.get((root, kind)):
            framework = "pytest"
        else:
            framework = "unknown"

        command = suite_command(root, framework, commands.get("test", []))
        if kind == "e2e" and framework in {"Playwright", "Cypress"}:
            command = DEFAULT_COMMANDS[framework]
        if command == DEFAULT_COMMANDS["unittest"] and root not in {".", ""}:
            # A root-level tests/ beside a separate package: name the start
            # directory, importable from the top (tests import the package).
            # (empty __init__.py files are not indexed, so infer package mode
            # from a nested root or from imports that need it)
            dotted = root.replace("/", ".")
            package = ("/" in root or f"{root}/__init__.py" in paths or any(
                re.search(rf"^\s*(?:from\s+{re.escape(dotted)}\b|import\s+{re.escape(dotted)}\.|from\s+\.)",
                          file_texts.get(r.path, ""), re.M) for r in records))
            command = f"python -m unittest discover -s {root}" + (" -t ." if package else "")

        suites.append(TestSuite(
            name=f"{root} ({kind})" if root != "." else kind,
            root=root, framework=framework, kind=kind,
            file_count=len(records), command=command,
        ))
    return suites[:24]


def coverage_signals(files: list[FileRecord],
                     file_texts: dict[str, str] | None = None) -> dict[str, object]:
    """Rough source-to-test balance. Not a coverage number — a smell detector.

    A source directory counts as exercised when a test lives in or beside it,
    or when any test file refers to it by import path or module name (a
    root-level `tests/` testing a separate package is the common case). Only
    directories with neither are listed, and only when test texts were read:
    without them nothing is claimed."""
    source = [f for f in files if f.role == "source"]
    tests = [f for f in files if f.role == "test"]
    source_loc = sum(f.lines for f in source) or 1
    test_loc = sum(f.lines for f in tests)

    tested_dirs = {str(PurePosixPath(f.path).parent) for f in tests}
    source_dirs = Counter(str(PurePosixPath(f.path).parent) for f in source)
    texts = [file_texts[f.path] for f in tests if file_texts and f.path in file_texts]
    corpus = "\n".join(texts)

    def referenced(directory: str) -> bool:
        parts = [p for p in PurePosixPath(directory).parts if p not in {"src", "lib", "main", "java", "."}]
        if not parts:
            return True
        dotted, slashed = ".".join(parts), "/".join(parts)
        if re.search(rf"\b(?:import|from)\s+{re.escape(dotted)}\b", corpus):
            return True
        if re.search(rf"""['"][^'"\n]*\b{re.escape(slashed)}\b""", corpus):
            return True
        modules = {PurePosixPath(f.path).stem for f in source if str(PurePosixPath(f.path).parent) == directory}
        return any(re.search(rf"\b{re.escape(m)}\b", corpus) for m in modules if len(m) > 2)

    untested = [
        d for d, count in source_dirs.most_common(200)
        if count >= 3 and not any(d in t or t.startswith(d) for t in tested_dirs)
        and texts and not referenced(d)
    ]
    return {
        "source_files": len(source),
        "test_files": len(tests),
        "test_to_source_loc_ratio": round(test_loc / source_loc, 3),
        "directories_without_nearby_tests": untested[:15],
    }


# --------------------------------------------------------------------------
# verification plan: what to run, in what role, and how sure we are
# --------------------------------------------------------------------------
# Functional correctness (tests) is the verification. Static analysis, type
# checks, builds and formatters are complementary and never stand in for it.
# Nothing here executes anything: repo-ai only describes commands.

_FORMATTERS = re.compile(r"\b(black|prettier|gofmt|rustfmt|isort|autopep8|yapf|clang-format|"
                         r"ruff format|cargo fmt|go fmt|dotnet format)\b|"
                         r"\b(?:run|make)\s+(?:format|fmt|prettier)(?::\w+)?\b")
_TYPECHECKERS = re.compile(r"\b(mypy|pyright|pytype|tsc|typecheck|type-check|types|flow check)\b")
# Runners a verification instruction may name. A declared command outside
# this list, or with shell plumbing, is listed in TESTING.md for review but
# never put into the always-loaded instructions.
_SAFE_HEADS = {
    "python", "python3", "pytest", "tox", "nox", "make", "npm", "pnpm", "yarn", "bun", "npx", "node",
    "deno", "go", "cargo", "mvn", "./mvnw", "gradle", "./gradlew", "dotnet", "bundle", "rake", "rspec",
    "composer", "vendor/bin/phpunit", "phpunit", "ruff", "mypy", "pyright", "flake8", "pylint",
    "eslint", "tsc", "uv", "poetry", "hatch", "pdm", "jest", "vitest", "mocha", "swift", "ctest",
    "black", "prettier", "isort", "gofmt", "rustfmt", "bazel", "sbt", "mix", "dart", "flutter",
}
_UNSAFE = re.compile(r"[;|`<>]|\$\(|&&|\|\||\b(curl|wget|sudo|rm|sh|bash|zsh|eval|exec|nc|ssh|scp|"
                     r"chmod|chown|dd|mkfs|docker|kubectl|git\s+push|pip\s+install|npm\s+install|"
                     r"publish|deploy|release)\b")
# Framework runners standard enough to infer from the tests themselves.
_INFERABLE = {"unittest", "pytest", "go test", "Testify", "Rust test", "xUnit", "NUnit", "MSTest"}


@dataclass(slots=True)
class VerifyCommand:
    command: str
    category: str  # tests | static | typecheck | format | build
    source: str    # declared (manifest, CI or docs) | inferred (from the test files)
    detail: str = ""


@dataclass(slots=True)
class VerificationPlan:
    tests: list[VerifyCommand] = field(default_factory=list)
    targeted: str = ""   # how to run one test or one file
    static: list[VerifyCommand] = field(default_factory=list)  # lint and type checks
    format: list[VerifyCommand] = field(default_factory=list)
    build: list[VerifyCommand] = field(default_factory=list)
    uncertain: str = ""  # why no trustworthy test command was established
    withheld: list[str] = field(default_factory=list)  # declared, but not safe to instruct

    @property
    def test_command(self) -> str:
        return self.tests[0].command if self.tests else ""


def command_category(command: str, bucket: str) -> str:
    if bucket == "test":
        return "tests"  # a declared test command is never reclassified by keyword
    if _FORMATTERS.search(command):
        return "format"
    if _TYPECHECKERS.search(command):
        return "typecheck"
    return {"test": "tests", "lint": "static", "build": "build"}.get(bucket, bucket)


def instructable(command: str) -> bool:
    """May this command appear in always-loaded agent instructions? Only plain
    invocations of a known runner (optionally scoped with `cd <dir> && `)."""
    scoped = re.match(r"^cd [\w./-]+ && (.+)$", command)
    body = scoped.group(1) if scoped else command
    words = body.split()
    return bool(words) and words[0] in _SAFE_HEADS and not _UNSAFE.search(body)


def targeted_form(framework: str, command: str) -> str:
    """A placeholder for running one test file or case with the same runner."""
    fw = (framework or "").lower()
    # the runner of the full-suite command decides; the framework only breaks ties
    if command.startswith("python -m pytest"):
        return "python -m pytest <path/to/test_file.py>"
    if command.startswith("pytest"):
        return "pytest <path/to/test_file.py>"
    if command.startswith("python -m unittest") or (fw == "unittest" and not command):
        return "python -m unittest <tests.test_module>"
    if fw in {"pytest", "fastapi testclient", "hypothesis"}:
        return "pytest <path/to/test_file.py>"
    if fw == "vitest":
        return "npx vitest run <path/to/file.test.ts>"
    if fw in {"jest", "testing library"}:
        return "npx jest <path/to/file.test.ts>"
    if fw in {"go test", "testify"}:
        return "go test ./<pkg>/ -run '<TestName>'"
    if "junit" in fw or fw in {"testng", "spring boot test", "mockito"}:
        return ("./gradlew test --tests '<ClassName>'" if "gradle" in command
                else "mvn test -Dtest=<ClassName>")
    if fw == "rust test":
        return "cargo test <name>"
    if fw in {"xunit", "nunit", "mstest"}:
        return "dotnet test --filter '<TestName>'"
    if fw == "rspec":
        return "bundle exec rspec <path/to/spec.rb>"
    return ""


def verification_plan(commands: dict[str, list[str]], suites: list[TestSuite]) -> VerificationPlan:
    plan = VerificationPlan()
    seen: set[str] = set()
    withheld_tests: list[str] = []

    def add(cmd: str, bucket: str, source: str, detail: str) -> None:
        if not cmd or cmd in seen:
            return
        seen.add(cmd)
        if not instructable(cmd):
            plan.withheld.append(cmd)
            if bucket == "test":
                withheld_tests.append(cmd)
            return
        category = command_category(cmd, bucket)
        item = VerifyCommand(cmd, category, source, detail)
        {"tests": plan.tests, "static": plan.static, "typecheck": plan.static,
         "format": plan.format, "build": plan.build}.get(category, []).append(item)

    for bucket in ("test", "lint", "build"):
        for cmd in commands.get(bucket) or []:
            add(cmd, bucket, "declared", "declared in the project's manifests, CI or docs")
    # the project's own root-level command leads; a `cd sub && ...` command
    # belongs to a nested package (or a fixture) and is never "the full suite"
    plan.tests.sort(key=lambda c: c.command.startswith("cd "))
    real = [s for s in suites if s.kind != "e2e"]
    if not plan.tests:
        for suite in real:
            if suite.framework in _INFERABLE and suite.command:
                where = f"`{suite.root}/`" if suite.root not in {".", ""} else "the repository"
                add(suite.command, "test", "inferred", f"inferred from the {suite.framework} tests in {where}")
    lead = next((s for s in real if s.command == plan.test_command), real[0] if real else None)
    if plan.tests:
        plan.targeted = targeted_form(lead.framework if lead else "", plan.test_command)
    elif withheld_tests:
        plan.uncertain = "the declared test command needs review before use (see TESTING.md)"
    elif not suites:
        plan.uncertain = "no test files were found"
    else:
        roots = ", ".join(f"`{s.root}/`" for s in suites[:3] if s.root not in {".", ""}) or "the repository"
        plan.uncertain = f"tests exist in {roots}, but no runner could be established"
    return plan


_HUMAN_TESTING = re.compile(r"(?im)^#{1,6}\s.*\b(test|tests|testing|verif\w*)\b")


def human_verification(human_text: str, plan: VerificationPlan) -> bool:
    """Do human-written instructions already say how to verify changes? (A
    testing heading, or a known test command.) Then repo-ai defers to them."""
    lower = human_text.lower()
    if _HUMAN_TESTING.search(human_text):
        return True
    return any(c.command.lower() in lower for c in plan.tests)


def verify_line(plan: VerificationPlan, human_has_testing: bool = False,
                static_commands: list[str] | None = None) -> str:
    """The always-loaded verification instruction: one short paragraph.
    `static_commands`: the static checks to mention (default: the plan's);
    the Claude block passes only those backed by an active learned rule."""
    honest = "If tests cannot run, say so; never report a change as verified without running them."
    chosen = [c.command for c in plan.static[:2]] if static_commands is None else static_commands[:2]
    static = ", ".join(f"`{c}`" for c in chosen)
    extra = f" Static checks ({static}) complement the tests, never replace them." if static else ""
    if human_has_testing:
        also = f" (repo-ai also detected `{plan.test_command}`)" if plan.test_command else ""
        return (f"**Verify** source changes as this project's own testing instructions say{also}."
                f"{extra} {honest}")
    if not plan.tests:
        return (f"**Verify** source changes: repo-ai could not establish a test command "
                f"({plan.uncertain}); find how this project runs its tests (CI, README) and run them."
                f"{extra} {honest}")
    lead = plan.tests[0]
    how = " (inferred from the tests; confirm it runs)" if lead.source == "inferred" else ""
    targeted = f" (e.g. `{plan.targeted}`)" if plan.targeted else ""
    return (f"**Verify** source changes: run the relevant tests{targeted}, then the full suite "
            f"`{lead.command}`{how} before finishing; a passing targeted test can hide a break elsewhere."
            f"{extra} {honest}")
