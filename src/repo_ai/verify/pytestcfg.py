"""Which name-matched test files pytest's `norecursedirs` keeps out of a full run, for a note only.

verify matches pytest test files by name until `repo-ai verify --record` has captured pytest's own collection, and it
never removes a file on a static reading of the configuration (a wrong reading would hide a test). But a targeted run
names files on pytest's command line, and pytest collects a named file even inside a `norecursedirs` directory; a
full run, which recurses, does not. So a targeted and a full run of one state can disagree (speed-v1: marshmallow's
`tests/mypy_test_cases`). This module reads `norecursedirs` from the configuration file pytest would use, to name
such files in the plan's uncertainty.

Deliberately narrow, so that a note is right when it appears: only `norecursedirs` (not `testpaths`, whose use
depends on how pytest is invoked); no note when the command chooses the configuration or rootdir itself (`-c`,
`--config-file`, `--rootdir`, `-o`/`--override-ini`, `--pyargs`); a parse error, a linked file or an oversized
value ends the search with no note. It parses text only and never imports or runs anything from the repository.
"""
from __future__ import annotations

import configparser
import fnmatch
import shlex
from pathlib import Path, PurePosixPath

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10
    import tomli as tomllib  # type: ignore[no-redef]

MAX_CONFIG_BYTES = 1_000_000
MAX_PATTERNS = 256
# pytest 9's lookup order within one directory (pytest 8 has no pytest.toml and no native [tool.pytest])
CANDIDATES = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
CONFIG_OPTIONS = ("-c", "--config-file", "--rootdir", "-o", "--override-ini", "--pyargs", "--inifile")
_STOP = object()  # pytest would use this file but it cannot be read here: no note, and no other file either


def _words(value: object) -> list[str] | None:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str)]
    if isinstance(value, str):
        try:
            return shlex.split(value)
        except ValueError:
            return value.split()
    return None


def _read(path: Path):
    """The settings of one candidate: a dict when pytest would use the file, None when pytest would look further,
    _STOP when pytest would use it but it cannot be read safely here."""
    try:
        if path.is_symlink():
            return _STOP if path.exists() else None
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_CONFIG_BYTES:
            return _STOP
        text = path.read_text("utf-8", errors="replace")
    except OSError:
        return None
    name = path.name
    try:
        if name.endswith(".toml"):
            data = tomllib.loads(text)
            if name == "pyproject.toml":
                tool = data.get("tool")
                pytest_table = tool.get("pytest") if isinstance(tool, dict) else None
                if not isinstance(pytest_table, dict):
                    return None
                if isinstance(pytest_table.get("ini_options"), dict):
                    section = pytest_table["ini_options"]
                else:
                    section = {k: v for k, v in pytest_table.items() if k != "ini_options"}
                    if not section:
                        return None  # an empty [tool.pytest]: pytest looks further
            else:  # pytest.toml / .pytest.toml: always the file; settings under [pytest]
                section = data.get("pytest") if isinstance(data.get("pytest"), dict) else {}
        else:
            parser = configparser.RawConfigParser(strict=False, interpolation=None, default_section="\0none")
            parser.optionxform = str  # type: ignore[assignment,method-assign]  # pytest's keys are case-sensitive
            parser.read_string(text, source=name)
            key = "tool:pytest" if name == "setup.cfg" else "pytest"
            if not parser.has_section(key):
                return None if name in {"tox.ini", "setup.cfg"} else {}  # pytest.ini is the file even when empty
            section = dict(parser.items(key))
    except (tomllib.TOMLDecodeError, configparser.Error, ValueError, RecursionError):
        return _STOP  # pytest itself would stop with an error here
    patterns = _words(section.get("norecursedirs")) if "norecursedirs" in section else []
    if patterns is None or len(patterns) > MAX_PATTERNS:
        return _STOP
    other = sorted(k for k in section if k in {"testpaths", "python_files", "addopts", "collect_ignore"})
    testpaths = _words(section.get("testpaths")) or []
    return {"norecursedirs": patterns, "other": other, "testpaths": testpaths[:MAX_PATTERNS]}


def find_config(root: Path, start: str = ""):
    """(repo-relative config file, settings) as pytest would pick it from `start` upward, inside the repository;
    None when there is none or it cannot be read safely."""
    root = root.resolve()
    cur = (root / start).resolve() if start else root
    if cur != root and root not in cur.parents:
        return None
    while True:
        for name in CANDIDATES:
            found = _read(cur / name)
            if found is _STOP:
                return None
            if found is not None:
                return (cur / name).relative_to(root).as_posix(), found
        if cur == root:
            return None
        cur = cur.parent


def _fnmatch_ex(pattern: str, path: PurePosixPath) -> bool:
    """pytest's `fnmatch_ex`: a pattern without a separator matches the basename, one with a separator the path's
    end."""
    if "/" not in pattern:
        return fnmatch.fnmatch(path.name, pattern)
    return fnmatch.fnmatch(str(path), pattern if pattern.startswith("/") else "*/" + pattern)


def _chooses_config(argv: list[str]) -> bool:
    for tok in argv:
        for opt in CONFIG_OPTIONS:
            if tok == opt or tok.startswith(opt + "="):
                return True
            if opt in {"-c", "-o"} and tok.startswith(opt) and len(tok) > 2:  # -cfile, -okey=value
                return True
        if tok.startswith("-") and not tok.startswith("--"):
            for letter in tok[1:]:  # a cluster of short flags such as -qc FILE
                if letter in "co":
                    return True
                if letter in "kmpWrn":  # takes a value: the rest of the token is that value
                    break
    return False


def skipped_by_config(root: Path, test_files: list[str], start: str = "", argv: list[str] | None = None,
                      paths: list[str] | None = None) -> tuple[str, list[str], dict[str, list[str]]]:
    """(config file, other collection settings present, {"norecursedirs <pattern>": [files]}) for name-matched test
    files a full pytest run would not reach because `norecursedirs` stops its recursion above them. Only directories
    strictly below where pytest starts (the command's paths, else `start`) count: pytest never applies
    `norecursedirs` to an initial path or its parents. Empty when the command chooses its own configuration."""
    if _chooses_config(argv or []):
        return "", [], {}
    base = PurePosixPath(start) if start not in {"", "."} else PurePosixPath()
    roots = [base / p for p in (paths or [])] or [base]
    search = base
    if paths:  # pytest searches from the common ancestor of its path arguments (a file counts as its directory)
        dirs_of = [r if (root / r).is_dir() else r.parent for r in roots]
        common = [*dirs_of[0].parts]
        for d in dirs_of[1:]:
            n = 0
            while n < min(len(common), len(d.parts)) and common[n] == d.parts[n]:
                n += 1
            common = common[:n]
        search = PurePosixPath(*common) if common else PurePosixPath()
    found = find_config(root, str(search) if str(search) not in {"", "."} else "")
    if found is None:
        return "", [], {}
    cfg_rel, settings = found
    # without path arguments, run from the configuration's directory, pytest starts from `testpaths`: never
    # apply norecursedirs to those entries or to their parents
    protected: set[PurePosixPath] = set()
    cfg_dir = PurePosixPath(cfg_rel).parent
    if not paths and (cfg_dir == base or (str(cfg_dir) == "." and str(base) in {"", "."})):
        for entry in settings["testpaths"]:
            if any(ch in entry for ch in "*?["):
                return "", [], {}  # a glob entry's starting points are not computed here: no note
            if entry.startswith("/"):
                continue
            target = PurePosixPath("/") / (cfg_dir / entry if str(cfg_dir) != "." else PurePosixPath(entry))
            protected |= {target, *target.parents}
    skipped: dict[str, list[str]] = {}
    for rel in test_files:
        p = PurePosixPath(rel)
        top = next((r for r in roots if str(r) in {"", "."} or r in p.parents), None)
        if top is None:
            continue
        below = p.relative_to(top) if str(top) not in {"", "."} else p
        anchored = PurePosixPath("/") / p  # pytest matches absolute paths: anchor so "*/a/b" can match "a/b"
        dirs = [d for d in (anchored.parents[i] for i in range(len(below.parts) - 1)) if d not in protected]
        for pat in settings["norecursedirs"]:
            if any(_fnmatch_ex(pat, d) for d in dirs):
                skipped.setdefault(f"norecursedirs {pat}", []).append(rel)
                break
    return cfg_rel, settings["other"], skipped
