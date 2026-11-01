"""Which name-matched test files pytest's own configuration would not collect, for a note only.

verify matches pytest test files by name until `repo-ai verify --record` has captured pytest's own collection, and it
never removes a file on a static reading of the configuration (a wrong reading would hide a test). But a targeted run
names files on pytest's command line, and pytest collects a named file even inside a `norecursedirs` directory or
outside `testpaths`; a full run does not. So a targeted and a full run of one state can disagree (speed-v1:
marshmallow's `tests/mypy_test_cases`). This module reads `norecursedirs` and `testpaths` from the configuration file
pytest would use, to name such files in the plan's uncertainty. It parses text only and never imports or runs
anything from the repository.
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
# pytest's lookup order within one directory (pytest 9 also reads pytest.toml and [tool.pytest])
CANDIDATES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "pyproject.toml", "tox.ini", "setup.cfg")


def _words(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float))]
    if isinstance(value, str):
        try:
            return shlex.split(value)
        except ValueError:
            return value.split()
    return []


def _read(path: Path) -> dict[str, list[str]] | None:
    """The [pytest] settings of one candidate file, or None when it is not pytest's configuration file."""
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_CONFIG_BYTES:
            return None
        text = path.read_text("utf-8", errors="replace")
    except OSError:
        return None
    name = path.name
    section: dict | None = None
    if name.endswith(".toml"):
        try:
            data = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError):
            return None
        if name == "pyproject.toml":
            tool = data.get("tool", {}).get("pytest") if isinstance(data.get("tool"), dict) else None
            if not isinstance(tool, dict):
                return None
            section = tool.get("ini_options") if isinstance(tool.get("ini_options"), dict) else tool
        else:
            section = data.get("pytest") if isinstance(data.get("pytest"), dict) else data
    else:
        parser = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            parser.read_string(text, source=name)
        except configparser.Error:
            return None
        key = "tool:pytest" if name == "setup.cfg" else "pytest"
        if not parser.has_section(key):
            return None if name in {"tox.ini", "setup.cfg"} else {}  # pytest.ini is the file even when empty
        section = dict(parser.items(key))
    return {k: _words(section.get(k)) for k in ("norecursedirs", "testpaths") if section.get(k) is not None}


def find_config(root: Path, start: str = "") -> tuple[str, dict[str, list[str]]] | None:
    """(repo-relative config file, settings) as pytest would pick it from `start` upward, inside the repository."""
    root = root.resolve()
    cur = (root / start).resolve() if start else root
    if cur != root and root not in cur.parents:
        cur = root
    while True:
        for name in CANDIDATES:
            if (cur / name).is_symlink():
                return None  # pytest would follow it; this reader does not, and naming another file would mislead
            found = _read(cur / name)
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


def skipped_by_config(root: Path, test_files: list[str], start: str = "") -> tuple[str, dict[str, list[str]]]:
    """(config file, {reason: [repo-relative files]}) for name-matched test files a full pytest run would not
    collect: under a `norecursedirs` directory, or outside every `testpaths` entry. Empty when nothing applies."""
    found = find_config(root, start)
    if found is None:
        return "", {}
    cfg_rel, settings = found
    base = PurePosixPath(cfg_rel).parent
    skipped: dict[str, list[str]] = {}
    for rel in test_files:
        p = PurePosixPath(rel)
        try:
            inside = p.relative_to(base) if str(base) != "." else p
        except ValueError:
            continue
        anchored = PurePosixPath("/") / p  # pytest matches absolute paths: anchor so "*/a/b" can match "a/b"
        dirs = [anchored.parents[i] for i in range(len(inside.parts) - 1)]
        for pat in settings.get("norecursedirs", []):
            if any(_fnmatch_ex(pat, d) for d in dirs):
                skipped.setdefault(f"norecursedirs {pat}", []).append(rel)
                break
        paths = settings.get("testpaths", [])
        if paths and not any(inside == PurePosixPath(t) or fnmatch.fnmatch(str(inside), t.rstrip("/") + "/*")
                             or PurePosixPath(t) in inside.parents for t in paths):
            skipped.setdefault("outside testpaths " + " ".join(paths), []).append(rel)
    return cfg_rel, skipped
