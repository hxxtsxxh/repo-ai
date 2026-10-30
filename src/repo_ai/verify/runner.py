"""How a project's tests are run: one argv per test file, one argv for a group
of files, and the full suite. Parsed from a trusted command (the verification
plan's, or one the user configured); never from repository prose.

Supported runners: ``unittest`` (discover or module lists), ``pytest`` and
``node --test``. Anything else is "opaque": it can be run as a whole, but
not split per file, so it gets no per-file selection or runtime evidence.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

PYTHONS = {"python", "python3", "{python}", "py"}
# node's own default test patterns. Since node 23.6 strips TypeScript types by default and its patterns
# take the .ts/.mts/.cts forms too: a `node --test` with no paths runs `*.test.mts`, so verify lists them
_NODE_PATTERNS = ("**/*.test.?(c|m)", "**/*-test.?(c|m)", "**/*_test.?(c|m)", "**/test-*.?(c|m)", "**/test.?(c|m)",
                  "**/test/**/*.?(c|m)")
NODE_DEFAULT_GLOBS = tuple(p + ext for ext in ("js", "ts") for p in _NODE_PATTERNS)
NODE_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts")


# environment a test command may set: search paths and pure-Python switches,
# repository-relative only (nothing that could load code from elsewhere)
SAFE_ENV = {"PYTHONPATH", "PURE_PYTHON", "PYTHONHASHSEED", "TZ", "LANG", "LC_ALL", "NODE_ENV"}


class RunnerError(ValueError):
    pass


@dataclass(slots=True)
class TestRunner:
    kind: str                       # unittest | pytest | node | opaque
    command: str                    # the trusted command it was parsed from (display)
    cwd: str = ""                   # repo-relative directory commands run in ("" = root)
    full: list[str] = field(default_factory=list)  # argv of the full suite (python/node as tokens)
    start: str = "."                # unittest discover start, relative to cwd
    top: str = "."                  # unittest top-level directory, relative to cwd
    pattern: str = "test*.py"
    modules: list[str] = field(default_factory=list)   # unittest module list (when given)
    paths: list[str] = field(default_factory=list)     # pytest / node explicit paths
    excluded: list[str] = field(default_factory=list)  # repo-relative test files never selected
    included: list[str] = field(default_factory=list)  # files pytest collects that the patterns miss
    env: dict[str, str] = field(default_factory=dict)  # leading VAR=value assignments (allowlisted)
    options: list[str] = field(default_factory=list)   # pytest/node options kept for per-file runs
    source: str = ""                # where the command came from (shown before anything runs)
    notes: list[str] = field(default_factory=list)     # each resolution or refinement rule applied

    def to_json(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, object]) -> TestRunner:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)  # type: ignore[arg-type]

    @property
    def language(self) -> str:
        return "node" if self.kind == "node" else "python"

    @property
    def per_file(self) -> bool:
        return self.kind in {"unittest", "pytest", "node"}

    # -- the test universe --------------------------------------------------
    def _rel(self, path: str) -> str:
        """repo-relative -> relative to cwd"""
        if not self.cwd:
            return path
        prefix = self.cwd.rstrip("/") + "/"
        if not path.startswith(prefix):
            raise RunnerError(f"{path} is outside the test runner's directory {self.cwd}")
        return path[len(prefix):]

    def _abs(self, rel: str) -> str:
        """relative to cwd -> repo-relative"""
        joined = PurePosixPath(self.cwd or ".") / rel
        parts: list[str] = []
        for part in joined.parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        return "/".join(parts)

    def test_files(self, repo_files: list[str], root: Path | None = None) -> list[str]:
        """Repo-relative files this runner treats as test files."""
        files = sorted(set(repo_files))
        if self.kind == "unittest":
            if self.modules:
                found = [self._abs(m.replace(".", "/") + ".py") for m in self.modules]
                out = [f for f in found if f in files]
            else:
                start = self._abs(self.start)
                out = []
                for f in files:
                    p = PurePosixPath(f)
                    if not f.endswith(".py") or not fnmatch.fnmatch(p.name, self.pattern):
                        continue
                    if start not in {"", "."} and not f.startswith(start.rstrip("/") + "/"):
                        continue
                    # unittest discovery only descends into packages
                    rel_dirs = p.parent.relative_to(start) if start not in {"", "."} else p.parent
                    ok = True
                    cur = PurePosixPath(start) if start not in {"", "."} else PurePosixPath()
                    for part in rel_dirs.parts:
                        cur = cur / part
                        if (cur / "__init__.py").as_posix() not in files:
                            ok = False
                            break
                    if ok:
                        out.append(f)
        elif self.kind == "pytest":
            roots = [self._abs(p) for p in self.paths] or [self.cwd or "."]
            out = [f for f in files if f.endswith(".py") and
                   (fnmatch.fnmatch(PurePosixPath(f).name, "test_*.py") or
                    fnmatch.fnmatch(PurePosixPath(f).name, "*_test.py")) and
                   any(r in {"", "."} or f == r or f.startswith(r.rstrip("/") + "/") for r in roots)]
        elif self.kind == "node":
            if self.paths:
                explicit = {self._abs(p) for p in self.paths}
                out = [f for f in files if f in explicit or any(
                    _glob_match(f, self._abs(p)) for p in self.paths if any(c in p for c in "*?["))]
            else:
                out = [f for f in files if f.endswith(NODE_SUFFIXES) and "node_modules/" not in f
                       and (not self.cwd or f.startswith(self.cwd.rstrip("/") + "/"))
                       and any(_glob_match(self._rel(f), g) for g in NODE_DEFAULT_GLOBS)]
        else:
            out = []
        present = set(files)
        out = sorted(set(out) | {f for f in self.included if f in present})
        return [f for f in out if f not in set(self.excluded)]

    # -- argv ---------------------------------------------------------------
    def file_argv(self, test_file: str) -> list[str]:
        rel = self._rel(test_file)
        if self.kind == "unittest" and self.top not in {"", "."}:
            # the top-level directory is not the working directory: let discovery set
            # up sys.path exactly as the full suite does, for just this one file
            p = PurePosixPath(rel)
            return ["python", "-m", "unittest", "discover", "-s", str(p.parent), "-t", self.top,
                    "-p", p.name]
        return self.group_argvs([test_file])[0]

    def group_argvs(self, test_files: list[str]) -> list[list[str]]:
        """As few invocations as possible that run exactly these test files."""
        if not test_files:
            return []
        rels = [self._rel(f) for f in test_files]
        if self.kind == "unittest":
            if self.top not in {"", "."}:
                return [self.file_argv(f) for f in test_files]
            mods = [".".join(PurePosixPath(rel).with_suffix("").parts) for rel in rels]
            return [["python", "-m", "unittest", *mods]]
        if self.kind == "pytest":
            return [["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *self.options, *rels]]
        if self.kind == "node":
            return [["node", *self.options, "--test", *rels]]
        raise RunnerError(f"the {self.kind} runner cannot run individual test files")

    def display(self, argv: list[str]) -> str:
        line = shlex.join(argv)
        if self.env:
            line = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(self.env.items())) + " " + line
        return f"cd {shlex.quote(self.cwd)} && {line}" if self.cwd else line


def _glob_match(path: str, pattern: str) -> bool:
    """Shell-style glob with ** and node's ?(a|b) extglob for the suffix."""
    import re
    rx = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            rx += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("?(", i):
            close = pattern.index(")", i)
            rx += "(?:" + "|".join(re.escape(x) for x in pattern[i + 2:close].split("|")) + ")?"
            i = close + 1
            continue
        rx += {"*": "[^/]*", "?": "[^/]"}.get(c, re.escape(c))
        i += 1
    return re.fullmatch(rx, path) is not None


def parse_command(command: str) -> TestRunner:
    """A runner for a trusted test command. Unknown shapes become opaque."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return TestRunner("opaque", command)
    cwd = ""
    if len(argv) >= 3 and argv[0] in {"sh", "bash"} and argv[1] == "-c":
        return parse_command(argv[2]) if len(argv) == 3 else TestRunner("opaque", command)
    if len(argv) >= 4 and argv[0] == "cd" and argv[2] == "&&":
        cwd = argv[1].strip("/")
        if cwd in {".", ""} or ".." in PurePosixPath(cwd).parts:
            return TestRunner("opaque", command)
        argv = argv[3:]
    env: dict[str, str] = {}
    while argv and "=" in argv[0] and not argv[0].startswith("-"):
        name, _, value = argv[0].partition("=")
        if name not in SAFE_ENV or ".." in PurePosixPath(value).parts or value.startswith("/"):
            return TestRunner("opaque", command, cwd=cwd)
        env[name] = value
        argv = argv[1:]
    if any(tok in {"&&", "||", ";", "|", ">", "<"} for tok in argv):
        return TestRunner("opaque", command, cwd=cwd)
    runner = _parse_argv(argv, command)
    runner.cwd = cwd
    runner.env = env
    return runner


def _parse_argv(argv: list[str], command: str) -> TestRunner:
    if not argv:
        return TestRunner("opaque", command)
    head = PurePosixPath(argv[0]).name
    rest = argv[1:]
    if head in PYTHONS or head.startswith("python3."):
        if rest[:2] == ["-m", "unittest"]:
            args = rest[2:]
            if not args or args[0] == "discover":
                opts = args[1:] if args else []
                start, top, pattern = ".", None, "test*.py"
                positional: list[str] = []
                i = 0
                while i < len(opts):
                    tok = opts[i]
                    if tok in {"-s", "--start-directory"} and i + 1 < len(opts):
                        start = opts[i + 1]
                        i += 2
                    elif tok in {"-t", "--top-level-directory"} and i + 1 < len(opts):
                        top = opts[i + 1]
                        i += 2
                    elif tok in {"-p", "--pattern"} and i + 1 < len(opts):
                        pattern = opts[i + 1]
                        i += 2
                    elif tok.startswith("-"):
                        i += 1
                    else:
                        positional.append(tok)
                        i += 1
                if positional:
                    start = positional[0]
                if len(positional) > 1:
                    pattern = positional[1]
                if len(positional) > 2:
                    top = positional[2]
                # unittest: without -t the top-level directory is the start directory
                top_dir = top if top is not None else start
                return TestRunner("unittest", command, full=["python", "-m", "unittest", *args],
                                  start=start.rstrip("/") or ".", top=top_dir.rstrip("/") or ".",
                                  pattern=pattern)
            mods = [a for a in args if not a.startswith("-")]
            if mods and all(_is_module(m) for m in mods):
                return TestRunner("unittest", command, full=["python", "-m", "unittest", *args],
                                  modules=mods)
            return TestRunner("opaque", command)
        if rest[:2] == ["-m", "pytest"]:
            return _pytest(rest[2:], command)
        return TestRunner("opaque", command)
    if head in {"pytest", "py.test"}:
        return _pytest(rest, command)
    if head == "node" and "--test" in rest:
        options, paths = _split_options(rest, NODE_VALUE_OPTIONS)
        options = [o for o in options if o != "--test" and not o.startswith(_NODE_COVERAGE_FLAGS)
                   and not o.startswith(("--watch", "--test-shard", "--test-only"))]
        return TestRunner("node", command, full=["node", *rest], paths=paths, options=options)
    return TestRunner("opaque", command)


# options whose value is the next token (`--import tsx`): not test paths
NODE_VALUE_OPTIONS = {"--import", "--require", "-r", "--loader", "--experimental-loader", "--conditions", "-C",
                      "--test-reporter", "--test-reporter-destination", "--test-name-pattern",
                      "--test-skip-pattern", "--test-concurrency", "--test-timeout", "--env-file", "--input-type"}
PYTEST_VALUE_OPTIONS = {"-m", "-k", "-p", "-c", "-o", "-W", "--rootdir", "--confcutdir", "--basetemp",
                        "--import-mode", "--override-ini", "--deselect", "--ignore", "--ignore-glob",
                        "-n", "--numprocesses", "--dist", "--maxfail", "--tb", "-r", "--durations"}
# never applied to a single file: coverage, parallelism, early exit across files
_PYTEST_DROP = ("--cov", "--no-cov", "-n", "--numprocesses", "--dist", "--maxfail", "-x", "--exitfirst",
                "--lf", "--ff", "--last-failed", "--failed-first", "--sw", "--stepwise")


def _split_options(args: list[str], takes_value: set[str]) -> tuple[list[str], list[str]]:
    options: list[str] = []
    paths: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("-"):
            if tok in takes_value and i + 1 < len(args):
                options += [tok, args[i + 1]]
                i += 2
                continue
            options.append(tok)
        else:
            paths.append(tok)
        i += 1
    return options, paths


def _pytest(args: list[str], command: str) -> TestRunner:
    options, positional = _split_options(args, PYTEST_VALUE_OPTIONS)
    paths = [a for a in positional if "::" not in a]
    kept: list[str] = []
    i = 0
    while i < len(options):
        tok = options[i]
        pair = tok in PYTEST_VALUE_OPTIONS and i + 1 < len(options)
        name = tok.split("=", 1)[0]
        if name in _PYTEST_DROP or name.startswith("--cov") or tok in {"-q", "-v", "-vv", "-qq"}:
            i += 2 if pair else 1
            continue
        kept += options[i:i + 2] if pair else [tok]
        i += 2 if pair else 1
    return TestRunner("pytest", command, full=["python", "-m", "pytest", *args], paths=paths, options=kept)


def _is_module(name: str) -> bool:
    return all(part.isidentifier() for part in name.split("."))


# lint, format and type checks a test script often chains before or after its
# tests; skipped (and named) when a per-file runner is established
CHECK_TOOLS = {"eslint", "biome", "standard", "prettier", "tsc", "tstyche", "tsd", "xo", "stylelint",
               "ruff", "flake8", "mypy", "pyright", "black", "isort", "pylint", "publint", "attw",
               "markdownlint", "dtslint"}
COVERAGE_WRAPPERS = {"c8", "nyc"}
PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
RUNNER_HEADS = PYTHONS | {"pytest", "py.test", "node"}
_NODE_COVERAGE_FLAGS = ("--experimental-test-coverage", "--test-coverage-")
_MAKE_NOISE = re.compile(r"^(?:coverage|python3? -m coverage)\s+(?:report|html|xml|json|erase|combine)\b|^echo\b")


def _resolve(root: Path, command: str, depth: int = 0) -> TestRunner:
    """Parse `command`, looking through what commonly wraps a test runner.
    Files are read, never executed; anything that is not plainly a supported
    runner stays opaque. Each rule applied is recorded in `notes`:

    - `npm`/`pnpm`/`yarn`/`bun run <script>` and `npm test`: the
      package.json script (and its `pre` script), one level at a time;
    - `make <target>`: a recipe whose only other lines report coverage;
    - `a && b`: the one step that is a test runner, when every other step is
      a lint, format or type check (named in the notes, not run);
    - coverage wrappers (`c8`, `nyc`, `coverage run -m`) and node's coverage
      thresholds, which cannot hold for a single file.
    """
    runner = parse_command(command)
    if runner.per_file:
        return _strip_node_coverage(runner)
    if depth >= 8:  # script chains are short; this also stops a script that calls itself
        return runner
    try:
        argv = shlex.split(command)
    except ValueError:
        return runner
    cwd = ""
    if len(argv) >= 4 and argv[0] == "cd" and argv[2] == "&&":
        cwd, argv = argv[1].strip("/"), argv[3:]
    prefix = f"cd {shlex.quote(cwd)} && " if cwd else ""
    base = root / cwd if cwd else root
    if any(tok in {"||", ";", "|", ">", "<", "&"} for tok in argv):
        return runner
    if "&&" in argv:
        return _chain(root, command, prefix, argv, depth)
    if not argv:
        return runner
    head = PurePosixPath(argv[0]).name
    inner, notes = "", []
    if head == "npx" and len(argv) > 1:
        argv, head = argv[1:], PurePosixPath(argv[1]).name
    if head in COVERAGE_WRAPPERS:
        at = next((i for i, tok in enumerate(argv[1:], 1) if PurePosixPath(tok).name in RUNNER_HEADS
                   or tok in PACKAGE_MANAGERS), 0)
        if at:
            inner, notes = shlex.join(argv[at:]), [f"coverage wrapper `{head}` is not used for per-file runs"]
    elif (head == "coverage" or (head in PYTHONS and argv[1:3] == ["-m", "coverage"])):
        rest = argv[1:] if head == "coverage" else argv[3:]
        if rest[:1] == ["run"] and "-m" in rest:
            m = rest.index("-m")
            inner = shlex.join(["python", *rest[m:]])
            notes = ["`coverage run` is not used for per-file runs"]
    elif head == "make" and len(argv) == 2 and argv[1].replace("-", "").replace("_", "").isalnum():
        inner = _make_recipe(base / "Makefile", argv[1])
        notes = [f"`{command}` runs `{inner}` (Makefile)"] if inner else []
    elif head in PACKAGE_MANAGERS:
        script = _script_name(head, argv[1:])
        if script:
            inner = _npm_script(base / "package.json", script)
            pre = _npm_script(base / "package.json", "pre" + script)
            if inner and pre:
                checked = _resolve(root, prefix + pre, depth + 1)
                if checked.kind != "check":
                    return runner  # a pre-script that is not a check (a build, say) must run first
                notes.append(f"`pre{script}` ({pre}) is a lint/type check: not run per file")
            if inner:
                notes.insert(0, f"`{command}` runs `{inner}` (package.json)")
    elif head in CHECK_TOOLS:
        return TestRunner("check", command, cwd=cwd)
    if not inner:
        return runner
    resolved = _resolve(root, prefix + inner, depth + 1)
    if resolved.kind == "check":
        return TestRunner("check", command, cwd=cwd)
    if not resolved.per_file:
        return runner
    resolved.command = command
    resolved.notes = notes + resolved.notes
    return resolved


def resolve(root: Path, command: str) -> TestRunner:
    """The runner for a trusted test command (see `_resolve`). A command that
    is only a lint or type check is opaque: it is not a test suite."""
    runner = _resolve(root, command)
    if runner.kind == "check":
        return TestRunner("opaque", command, cwd=runner.cwd, notes=["a lint/type check, not a test runner"])
    return runner


def _chain(root: Path, command: str, prefix: str, argv: list[str], depth: int) -> TestRunner:
    steps: list[list[str]] = [[]]
    for tok in argv:
        if tok == "&&":
            steps.append([])
        else:
            steps[-1].append(tok)
    found: list[TestRunner] = []
    skipped: list[str] = []
    for step in steps:
        if not step:
            return TestRunner("opaque", command)
        text = shlex.join(step)
        r = _resolve(root, prefix + text, depth + 1)
        if r.per_file:
            found.append(r)
        elif r.kind == "check":
            skipped.append(text)
        else:
            return TestRunner("opaque", command)  # a build or other step the tests may depend on
    if not found and skipped:
        return TestRunner("check", command)
    if len(found) != 1:
        return TestRunner("opaque", command)
    runner = found[0]
    runner.command = command
    runner.notes += [f"`{s}` is a lint/type check: not run per file" for s in skipped]
    return runner


def _script_name(manager: str, args: list[str]) -> str:
    args = [a for a in args if a not in {"--silent", "-s", "--if-present"}]
    if args in (["test"], ["t"]) and manager != "bun":
        return "test"
    if len(args) == 2 and args[0] in {"run", "run-script"}:
        return args[1]
    if len(args) == 1 and manager in {"pnpm", "yarn"} and args[0] not in {"install", "add", "exec", "dlx"}:
        return args[0]
    return ""


def _strip_node_coverage(runner: TestRunner) -> TestRunner:
    if runner.kind != "node":
        return runner
    kept = [a for a in runner.full if not a.startswith(_NODE_COVERAGE_FLAGS)]
    if kept != runner.full:
        runner.full = kept
        runner.notes.append("node coverage thresholds are not applied to per-file runs")
    return runner


def _make_recipe(makefile: Path, target: str) -> str:
    try:
        text = makefile.read_text("utf-8", errors="replace")[:200_000]
    except OSError:
        return ""
    variables: dict[str, str] = {}
    for m in re.finditer(r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\s*(\?|:)?=\s*(.*)$", text):
        variables.setdefault(m.group(1), m.group(3).strip())
    recipe = re.search(rf"(?m)^{re.escape(target)}\s*:[^=\n]*\n((?:\t.*\n?)+)", text)
    if not recipe:
        return ""
    lines = [ln.strip().lstrip("@-").strip() for ln in recipe.group(1).splitlines() if ln.strip()]
    lines = [ln for ln in lines if not _MAKE_NOISE.match(ln)]
    if len(lines) != 1:
        return ""  # several steps: not a single test invocation
    line = lines[0]
    for _ in range(5):  # variables defined through other variables: `python=$(venv)/bin/python`
        expanded = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", lambda v: variables.get(v.group(1), v.group(0)), line)
        if expanded == line:
            break
        line = expanded
    return "" if "$" in line else line


def _npm_script(package_json: Path, name: str) -> str:
    import json
    try:
        data = json.loads(package_json.read_text("utf-8"))
    except (OSError, ValueError):
        return ""
    script = (data.get("scripts") or {}).get(name) if isinstance(data, dict) else None
    return script if isinstance(script, str) else ""
