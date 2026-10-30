"""The exact fingerprint changes whenever a byte the workspace copies (and a
test can read) changes, and only then: line endings under git's own
conversion, deleted flagged files, and nothing for what is never copied
(untracked files inside a submodule, the absent files of a sparse checkout).
Found by an independent review of the fingerprint fix."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import _git, _write

from repo_ai.verify import changes


def _repo(tmp_path: Path, files: dict[str, str], autocrlf: str = "false") -> Path:
    root = tmp_path / "p"
    for rel, text in files.items():  # exact bytes: Path.write_text would write CRLF on Windows
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode())
    _git(root, "init", "-q", "-b", "main")
    # these tests say which conversion applies: never the machine's own (GitHub's Windows runners set
    # core.autocrlf=true globally)
    _git(root, "config", "core.autocrlf", autocrlf)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


BASE = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n",
        "tests/__init__.py": "", "tests/golden.txt": "3\n", "tests/test_core.py": "import unittest\n"}


def test_a_line_ending_change_under_text_auto_changes_the_fingerprint(tmp_path: Path):
    root = _repo(tmp_path, {".gitattributes": "* text=auto\n", **BASE})
    (root / "calc" / "core.py").write_bytes(b"def add(a, b):\n    return b + a\n")
    before = changes.detect(root)
    (root / "tests" / "golden.txt").write_bytes(b"3\r\n")  # git diff shows nothing: it compares after conversion
    after = changes.detect(root)
    assert after.fingerprint != before.fingerprint
    assert "tests/golden.txt" in [f.path for f in after.files]
    assert changes.fingerprint(root) == after.fingerprint


def test_without_conversion_configured_unchanged_files_stay_out_of_the_change(tmp_path: Path):
    root = _repo(tmp_path, BASE)
    (root / "calc" / "core.py").write_bytes(b"def add(a, b):\n    return b + a\n")
    assert [f.path for f in changes.detect(root).files] == ["calc/core.py"]


def test_a_deleted_flagged_file_is_a_deletion(tmp_path: Path):
    for flag in ("--assume-unchanged", "--skip-worktree"):
        root = _repo(tmp_path / flag.strip("-"), BASE)
        _git(root, "update-index", flag, "tests/golden.txt")
        before = changes.fingerprint(root)
        (root / "tests" / "golden.txt").unlink()
        after = changes.detect(root)
        assert after.fingerprint != before, flag
        assert [(f.path, f.status) for f in after.files] == [("tests/golden.txt", "deleted")], flag


def test_the_absent_files_of_a_sparse_checkout_are_not_a_change(tmp_path: Path):
    root = _repo(tmp_path, {**BASE, "docs/big.txt": "x\n"})
    _git(root, "sparse-checkout", "set", "--no-cone", "/*", "!/docs/")
    assert not (root / "docs" / "big.txt").exists()
    assert changes.detect(root).files == []


def test_an_untracked_file_inside_a_submodule_is_not_a_change(tmp_path: Path):
    vend = tmp_path / "vend"
    _write(vend, {"vlib.py": "def three():\n    return 3\n"})
    _git(vend, "init", "-q", "-b", "main")
    _git(vend, "add", "-A")
    _git(vend, "commit", "-qm", "v")
    root = _repo(tmp_path, BASE)
    subprocess.run(["git", "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(vend), "vend"], cwd=root,
                   check=True, capture_output=True)
    _git(root, "commit", "-qm", "sub")
    before = changes.fingerprint(root)
    (root / "vend" / "notes.txt").write_text("scratch\n")  # never copied into a workspace
    assert changes.fingerprint(root) == before
    (root / "vend" / "vlib.py").write_text("def three():\n    return 4\n")  # copied: a change
    assert changes.fingerprint(root) != before


def _bytes(root: Path, rel: str, data: bytes) -> None:
    (root / rel).write_bytes(data)


def test_with_autocrlf_a_line_ending_flip_changes_the_fingerprint_either_way(tmp_path: Path):
    """With core.autocrlf=true a CRLF file is what a checkout writes, so it is not "different from the
    base" by git's measure, yet the copy and the tests read its bytes. Both directions of a flip change
    the exact fingerprint; selection is unaffected."""
    root = _repo(tmp_path, BASE, autocrlf="true")
    _bytes(root, "tests/golden.txt", b"3\r\n")
    (root / "calc" / "core.py").write_bytes(b"def add(a, b):\r\n    return b + a\r\n")
    crlf = changes.detect(root)
    _bytes(root, "tests/golden.txt", b"3\n")
    lf = changes.detect(root)
    assert crlf.fingerprint != lf.fingerprint
    assert changes.fingerprint(root) == lf.fingerprint
    _bytes(root, "tests/golden.txt", b"3\r\n")
    assert changes.fingerprint(root) == crlf.fingerprint
