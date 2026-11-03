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


def test_case_folded_state_paths_and_dunder_names(tmp_path):
    root = _repo(tmp_path, '[tool.setuptools_scm]\nversion_file = ".REPO-AI/_version.py"\n', FILES)
    assert isolate.generated_version_files(root) == []
    (tmp_path / "b").mkdir()
    root2 = _repo(tmp_path / "b", '[tool.setuptools_scm]\nversion_file = "src/pkg/__version__.py"\n', FILES)
    (root2 / "src/pkg/__version__.py").write_text("v = '1'\n", encoding="utf-8")
    assert isolate.generated_version_files(root2) == ["src/pkg/__version__.py"]


def test_a_link_or_file_in_the_way_leaves_the_version_file_out_without_failing(tmp_path):
    files = {**FILES, ".gitignore": "build/\n"}
    root = _repo(tmp_path, '[tool.setuptools_scm]\nversion_file = "src/gen/_version.py"\n', files)
    (root / "build").mkdir()
    (root / "build/_version.py").write_text("v = '1'\n", encoding="utf-8")
    (root / "src/gen").symlink_to("../build")  # a tracked directory link inside the repository
    subprocess.run(["git", "add", "src/gen"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "link"],
                   cwd=root, check=True)
    ws = isolate.materialize(root, dependencies=False)
    try:
        assert ws.generated == []
    finally:
        isolate._remove(ws.path)


def test_a_copied_version_file_is_not_blamed_on_the_provider(tmp_path):
    """journey-live-v1 (C21, humanize): repo-ai itself copied the declared version file into the candidate, then
    refused the provider's result for "creating" it. Only a version file the provider changed is refused."""
    from repo_ai.providers.adapters import validate_workspace_edits
    files = {**FILES, "src/pkg/core.py": "def f():\n    return 1\n"}
    root = _repo(tmp_path, HATCH, files)
    (root / "src/pkg/_version.py").write_text("v = '1.2.3'\n", encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    tracked = set(subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split())
    with isolate.materialize_commit(root, head, label="t-gen") as ws:
        assert ws.generated == ["src/pkg/_version.py"]
        (ws.path / "src/pkg/core.py").write_text("def f():\n    return 2\n")  # the provider's edit
        problems = validate_workspace_edits(root, ws.path, ["src/pkg/core.py"], set(), tracked,
                                            generated=dict(ws.generated_sha256))
        assert not any("_version.py" in p for p in problems), problems
        (ws.path / "src/pkg/_version.py").write_text("v = 'changed by the provider'\n")
        changed = validate_workspace_edits(root, ws.path, ["src/pkg/core.py"], set(), tracked,
                                           generated=dict(ws.generated_sha256))
        assert any("modified a generated version file: src/pkg/_version.py" in p for p in changed), changed


@pytest.mark.parametrize("change", ["deleted", "directory", "oversized"])
def test_a_removed_or_replaced_version_file_is_refused(tmp_path, change):
    from repo_ai.mission.contracts import MAX_SOURCE_FILE
    from repo_ai.providers.adapters import validate_workspace_edits
    files = {**FILES, "src/pkg/core.py": "def f():\n    return 1\n"}
    root = _repo(tmp_path, HATCH, files)
    (root / "src/pkg/_version.py").write_text("v = '1.2.3'\n", encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    tracked = set(subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split())
    with isolate.materialize_commit(root, head, label="t-gen2") as ws:
        (ws.path / "src/pkg/core.py").write_text("def f():\n    return 2\n")
        target = ws.path / "src/pkg/_version.py"
        target.unlink()
        if change == "directory":
            target.mkdir()
        elif change == "oversized":
            target.write_bytes(b"#" * (MAX_SOURCE_FILE + 10))
        problems = validate_workspace_edits(root, ws.path, ["src/pkg/core.py"], set(), tracked,
                                            generated=dict(ws.generated_sha256))
        assert any("modified a generated version file: src/pkg/_version.py" in p for p in problems), problems


def test_the_checkouts_version_file_changing_during_the_run_is_not_blamed_on_the_provider(tmp_path):
    from repo_ai.providers.adapters import validate_workspace_edits
    files = {**FILES, "src/pkg/core.py": "def f():\n    return 1\n"}
    root = _repo(tmp_path, HATCH, files)
    (root / "src/pkg/_version.py").write_text("v = '1.2.3'\n", encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    tracked = set(subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split())
    with isolate.materialize_commit(root, head, label="t-gen3") as ws:
        (ws.path / "src/pkg/core.py").write_text("def f():\n    return 2\n")
        (root / "src/pkg/_version.py").write_text("v = '1.2.4.dev1'\n")  # an editable reinstall, say
        problems = validate_workspace_edits(root, ws.path, ["src/pkg/core.py"], set(), tracked,
                                            generated=dict(ws.generated_sha256))
        assert not any("_version.py" in p for p in problems), problems
