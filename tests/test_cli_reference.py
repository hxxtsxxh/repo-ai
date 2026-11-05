"""The committed CLI reference matches the parser (scripts/gen_cli_reference.py)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gen_cli_reference.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not shipped in the sdist")


def _gen():
    spec = importlib.util.spec_from_file_location("gen_cli_reference", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_reference_is_current():
    gen = _gen()
    for path, text in gen.targets().items():
        assert path.read_text(encoding="utf-8") == text, (
            f"{path.relative_to(ROOT)} is stale: run python scripts/gen_cli_reference.py")


def test_cli_reference_lists_every_visible_command():
    gen = _gen()
    from repo_ai.cli import build_parser
    body = gen.render()
    names = [name for name, _aliases, _help, _p in gen._subcommands(build_parser())]
    assert {"verify", "do", "coverage", "shortlist", "agents", "apply", "undo"} <= set(names)
    for name in names:
        assert f"## `repo-ai {name}`" in body
    assert "_extract-prompt" not in body  # internal command registered without help
