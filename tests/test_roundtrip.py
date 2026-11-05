"""Install → uninstall restores human-owned files byte for byte.

Covers line endings (CRLF), JSON formatting styles, human edits made while
repo-ai is installed (never reverted), CRLF checkouts of repo-ai's own files
(git autocrlf on Windows), and console encodings that cannot show Unicode.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from conftest import commit_all, run_cli, snapshot

SETTINGS_STYLES = {
    "compact-mixed": (
        '{\n  "permissions": {\n    "allow": ["Bash(pytest:*)"],\n    "deny": ["Read(./.env)"]\n  },\n'
        '  "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo team-stop"}]}]}\n}\n'),
    "single-line": '{"permissions":{"deny":["Read(./.env)"]},"env":{"A":"1"}}',
    "single-line-spaced": '{"permissions": {"deny": ["Read(./.env)"]}}\n',
    "four-space": '{\n    "permissions": {\n        "deny": [\n            "Read(./.env)"\n        ]\n    }\n}\n',
    "tabs": '{\n\t"env": {\n\t\t"TEAM": "équipe"\n\t}\n}\n',
    "crlf": '{\r\n  "permissions": {\r\n    "ask": [\r\n      "Bash(git push:*)"\r\n    ]\r\n  }\r\n}\r\n',
    "unicode-escaped": '{\n  "env": {\n    "NAME": "caf\\u00e9"\n  }\n}\n',
    "no-final-newline": '{\n  "env": {\n    "X": "1"\n  }\n}',
}


def _write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8"))


@pytest.mark.parametrize("style", sorted(SETTINGS_STYLES))
def test_settings_json_round_trips_byte_for_byte(pyweb: Path, style: str):
    original = SETTINGS_STYLES[style]
    _write(pyweb / ".claude" / "settings.json", original)
    commit_all(pyweb, "team settings")
    assert run_cli(pyweb, "init", "--agent", "claude", "--smart", "-q").returncode == 0
    installed = (pyweb / ".claude" / "settings.json").read_bytes().decode("utf-8")
    data = json.loads(installed)
    assert any("repo-ai" in h["command"] for e in data["hooks"]["UserPromptSubmit"] for h in e["hooks"])
    # the user's values survive, unchanged, while installed
    original_data = json.loads(original)
    for key, value in original_data.items():
        if key != "hooks":
            assert data[key] == value
    # the user's line endings survive while installed
    assert ("\r\n" in installed) == ("\r\n" in original)
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert (pyweb / ".claude" / "settings.json").read_bytes() == original.encode("utf-8")


def test_settings_style_is_kept_while_installed(pyweb: Path):
    _write(pyweb / ".claude" / "settings.json", SETTINGS_STYLES["four-space"])
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    text = (pyweb / ".claude" / "settings.json").read_text("utf-8")
    assert '\n    "permissions": {\n        "deny": [' in text
    _write(pyweb / ".claude" / "settings.json", SETTINGS_STYLES["tabs"])
    assert run_cli(pyweb, "update", "-q").returncode == 0
    text = (pyweb / ".claude" / "settings.json").read_text("utf-8")
    assert '\n\t"env": {\n\t\t"TEAM": "équipe"' in text  # tabs and literal Unicode kept


def test_settings_edited_while_installed_keeps_the_edit(pyweb: Path):
    _write(pyweb / ".claude" / "settings.json", SETTINGS_STYLES["single-line"])
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    path = pyweb / ".claude" / "settings.json"
    data = json.loads(path.read_text("utf-8"))
    data["permissions"]["deny"].append("Bash(curl:*)")
    path.write_text(json.dumps(data, indent=2) + "\n")
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    after = json.loads(path.read_text("utf-8"))
    assert after == {"permissions": {"deny": ["Read(./.env)", "Bash(curl:*)"]}, "env": {"A": "1"}}


def test_crlf_markdown_and_gitignore_round_trip(pyweb: Path):
    claude_md = "# Team\r\n\r\nUse tabs.\r\n"
    agents_md = "# Agents\r\n\r\nBe brief.\r\n"
    gitignore = (pyweb / ".gitignore").read_text("utf-8").replace("\n", "\r\n") \
        if (pyweb / ".gitignore").exists() else "node_modules/\r\n"
    _write(pyweb / "CLAUDE.md", claude_md)
    _write(pyweb / "AGENTS.md", agents_md)
    _write(pyweb / ".gitignore", gitignore)
    commit_all(pyweb, "crlf files")
    before = snapshot(pyweb)
    assert run_cli(pyweb, "init", "--agent", "both", "--smart", "-q").returncode == 0
    for name in ("CLAUDE.md", "AGENTS.md", ".gitignore"):
        raw = (pyweb / name).read_bytes()
        assert b"\n" not in raw.replace(b"\r\n", b""), f"{name} gained bare LF line endings"
    assert run_cli(pyweb, "init", "--agent", "both", "--smart", "-q").returncode == 0
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert snapshot(pyweb) == before


def test_markdown_without_final_newline_round_trips(pyweb: Path):
    _write(pyweb / "CLAUDE.md", "# Notes\n\nNo newline at the end")
    before = snapshot(pyweb)
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert snapshot(pyweb) == before


def test_human_edit_while_installed_is_never_reverted(pyweb: Path):
    _write(pyweb / "CLAUDE.md", "# Notes\n\nOriginal rule.\n")
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    path = pyweb / "CLAUDE.md"
    path.write_text(path.read_text("utf-8").replace("Original rule.", "Edited rule."))
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert path.read_text("utf-8") == "# Notes\n\nEdited rule.\n"


def test_per_agent_uninstall_restores_shared_file(pyweb: Path):
    _write(pyweb / "CLAUDE.md", "# Team\n\nKeep it short.")
    original = (pyweb / "CLAUDE.md").read_bytes()
    assert run_cli(pyweb, "init", "--agent", "both", "-q").returncode == 0
    assert run_cli(pyweb, "uninstall", "--agent", "claude", "-y").returncode == 0
    assert (pyweb / "CLAUDE.md").read_bytes() == original
    assert (pyweb / ".bob").is_dir()


def test_crlf_checkout_of_managed_files_is_still_owned(pyweb: Path):
    """git autocrlf rewrites repo-ai's own files with CRLF on Windows: they
    must still count as pristine — not rewritten, and removed on uninstall."""
    before = snapshot(pyweb)
    assert run_cli(pyweb, "init", "--agent", "claude", "--smart", "-q").returncode == 0
    owned = [p for p in (pyweb / ".claude").rglob("*") if p.is_file() and p.suffix == ".md"]
    assert owned
    for path in owned:
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    crlf = {p: p.read_bytes() for p in owned}
    assert run_cli(pyweb, "init", "--agent", "claude", "--smart", "-q").returncode == 0
    for path, data in crlf.items():
        assert path.read_bytes() == data, f"{path.name} was rewritten although unchanged"
    doctor = run_cli(pyweb, "doctor", "--agent", "claude", "--json")
    assert "edited by hand" not in doctor.stdout
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert snapshot(pyweb) == before


def test_output_survives_a_console_that_cannot_encode_unicode(pyweb: Path):
    proc = run_cli(pyweb, "init", "--agent", "claude", "--dry-run", "--diff",
                   env={"PYTHONIOENCODING": "ascii"})
    assert proc.returncode == 0, proc.stderr
    assert "+++ b/CLAUDE.md" in proc.stdout


def test_non_utf8_pipe_is_switched_to_utf8(monkeypatch):
    from repo_ai import cli
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    cli._configure_streams()
    print("a → b ✓")
    out.flush()
    assert out.buffer.getvalue().decode("utf-8").strip() == "a → b ✓"


def test_manifest_commands_use_posix_separators_on_every_host(tmp_path: Path):
    from repo_ai.manifests import parse_manifest
    commands: dict[str, list[str]] = {}
    parse_manifest(tmp_path, "services/api/Makefile", "test:\n\tpytest\n", commands)
    parse_manifest(tmp_path, "web/app/package.json", '{"scripts": {"build": "vite build"}}', commands)
    flat = [c for group in commands.values() for c in group]
    assert "make -C services/api test" in flat
    assert "cd web/app && npm run build" in flat
    assert not any("\\" in c for c in flat)
