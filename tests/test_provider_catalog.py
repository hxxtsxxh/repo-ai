"""The provider catalog states what repo-ai can do with each agent; detection never runs anything."""
from __future__ import annotations

import json
import os
import subprocess

from repo_ai.providers import catalog
from repo_ai.providers.discovery import PROVIDERS


def test_bundled_catalog_is_valid_and_matches_the_adapters():
    data = catalog.load()
    states = {p["id"]: p["repo_ai"] for p in data["providers"]}
    assert set(PROVIDERS) <= set(states)
    assert {i for i, s in states.items() if s in {"EXECUTION", "BLOCKED"}} == set(PROVIDERS)
    assert all(p["basis"] == "docs" for p in data["providers"] if p["repo_ai"] == "PLANNED")


def test_labels_cannot_be_inflated():
    data = catalog.load()
    bad = json.loads(json.dumps(data))
    next(p for p in bad["providers"] if p["id"] == "qwen-code")["repo_ai"] = "EXECUTION"
    assert any("qwen-code" in p for p in catalog.validate(bad))
    bad = json.loads(json.dumps(data))
    next(p for p in bad["providers"] if p["id"] == "claude")["repo_ai"] = "PLANNED"
    assert any("claude" in p for p in catalog.validate(bad))


def test_detection_is_a_path_lookup_and_refuses_repository_executables(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    marker = tmp_path / "ran"
    for name in ("qwen", "claude"):
        exe = repo / "bin" / name
        exe.write_text(f"#!/bin/sh\ntouch {marker}\n")
        exe.chmod(0o755)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    goose = elsewhere / "goose"
    goose.write_text(f"#!/bin/sh\ntouch {marker}\n")
    goose.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PATH", os.pathsep.join([str(repo / "bin"), str(elsewhere)]))
    rows = {r["id"]: r for r in catalog.detect(repo)}
    assert rows["qwen-code"]["presence"] == "UNTRUSTED_EXECUTABLE"
    assert rows["claude"]["presence"] == "UNTRUSTED_EXECUTABLE"
    assert rows["goose"]["presence"] == "INSTALLED_NO_ADAPTER"
    assert rows["codex"]["presence"] == "NOT_FOUND"
    assert not marker.exists()


def test_generic_names_are_not_used_for_detection():
    for p in catalog.load()["providers"]:
        assert not {"agent", "q", "cn"} & set(p["executables"])


def test_codex_prefers_a_dedicated_login_and_never_copies_more_than_its_two_files(tmp_path, monkeypatch):
    from pathlib import Path
    from repo_ai.providers import adapters
    real = tmp_path / "real"
    (real / ".codex" / "sessions").mkdir(parents=True)
    (real / ".codex" / "auth.json").write_text("personal")
    (real / ".codex" / "sessions" / "s.jsonl").write_text("history")
    ded = tmp_path / "ded"
    ded.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: real))
    monkeypatch.setenv("REPO_AI_CODEX_HOME", str(ded))
    assert adapters.codex_login_source() == "personal"
    (ded / "auth.json").write_text("dedicated")
    assert adapters.codex_login_source() == "dedicated"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    adapters._seed_live_provider_auth("codex", scratch)
    assert (scratch / ".codex" / "auth.json").read_text() == "dedicated"
    assert sorted(p.name for p in (scratch / ".codex").iterdir()) == ["auth.json"]
