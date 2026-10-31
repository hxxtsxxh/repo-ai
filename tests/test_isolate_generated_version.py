"""A version file the build backend writes (and git ignores) is part of the isolated copy, and nothing else ignored is.

Found by speed-v1 (benchmarks/speed-v1/RESULTS.md): humanize declares hatch-vcs `version-file =
"src/humanize/_version.py"`; the copy left it out, so every test failed with `No module named 'humanize._version'`
at base and change alike while the native suite passed."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repo_ai.verify import isolate


def _repo(tmp_path: Path, pyproject: str, files: dict[str, str]) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=root, check=True)
    subprocess.run([*git, "add", "-A"], cwd=root, check=True)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=root, check=True)
    return root


HATCH = '[tool.hatch.build.hooks.vcs]\nversion-file = "src/pkg/_version.py"\n'
SCM = '[tool.setuptools_scm]\nversion_file = "src/pkg/_version.py"\n'
FILES = {".gitignore": "src/pkg/_version.py\nlocal_settings.py\n", "src/pkg/__init__.py": "from ._version import v\n"}


@pytest.mark.parametrize("pyproject", [HATCH, SCM, '[tool.setuptools_scm]\nwrite_to = "src/pkg/_version.py"\n'])
def test_the_declared_version_file_is_copied(tmp_path, pyproject):
    root = _repo(tmp_path, pyproject, FILES)
    (root / "src/pkg/_version.py").write_text("v = '1.2.3'\n", encoding="utf-8")
    (root / "local_settings.py").write_text("TOKEN = 'not for tests'\n", encoding="utf-8")
    assert isolate.generated_version_files(root) == ["src/pkg/_version.py"]
    ws = isolate.materialize(root, dependencies=False)
    try:
        assert (ws.path / "src/pkg/_version.py").read_text() == "v = '1.2.3'\n"
        assert ws.generated == ["src/pkg/_version.py"] and "src/pkg/_version.py" in ws.files
        assert not (ws.path / "local_settings.py").exists(), "other ignored files stay out"
    finally:
        isolate._remove(ws.path)
    base = isolate.materialize_commit(root, "HEAD", dependencies=False)
    try:
        assert (base.path / "src/pkg/_version.py").exists() and base.generated == ["src/pkg/_version.py"]
    finally:
        isolate._remove(base.path)


def test_nothing_is_copied_without_a_declaration(tmp_path):
    root = _repo(tmp_path, "[project]\nname = 'pkg'\n", FILES)
    (root / "src/pkg/_version.py").write_text("v = '1'\n", encoding="utf-8")
    assert isolate.generated_version_files(root) == []
    ws = isolate.materialize(root, dependencies=False)
    try:
        assert not (ws.path / "src/pkg/_version.py").exists() and ws.generated == []
    finally:
        isolate._remove(ws.path)


@pytest.mark.parametrize("declared", ["local_settings.py", "../outside/_version.py", "/etc/_version.py",
                                      ".git/_version.py", "src/pkg/_version.txt", "src/pkg/.env"])
def test_a_declaration_cannot_name_an_arbitrary_file(tmp_path, declared):
    root = _repo(tmp_path, f'[tool.setuptools_scm]\nversion_file = "{declared}"\n', FILES)
    (root / "local_settings.py").write_text("TOKEN = 'x'\n", encoding="utf-8")
    assert isolate.generated_version_files(root) == []


def test_a_linked_or_oversized_version_file_is_refused(tmp_path):
    root = _repo(tmp_path, SCM, FILES)
    (root / "secret.txt").write_text("x", encoding="utf-8")
    (root / "src/pkg/_version.py").symlink_to(root / "secret.txt")
    assert isolate.generated_version_files(root) == []
    (root / "src/pkg/_version.py").unlink()
    (root / "src/pkg/_version.py").write_text("#" * (isolate.MAX_VERSION_FILE + 1), encoding="utf-8")
    assert isolate.generated_version_files(root) == []


def test_a_malformed_pyproject_copies_nothing(tmp_path):
    root = _repo(tmp_path, "[tool.setuptools_scm\nversion_file = ", FILES)
    assert isolate.generated_version_files(root) == []
