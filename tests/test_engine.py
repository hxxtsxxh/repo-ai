"""Engine regressions: one test per v0.4 defect, plus incremental == rebuild."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

from conftest import commit_all, make_repo, run_cli

from repo_ai.config import load_config
from repo_ai.index import SCHEMA_VERSION, fts_escape, open_index
from repo_ai.manifests import parse_manifest, parse_pom
from repo_ai.paths import resolve_layout

TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ROOT = Path(__file__).resolve().parent.parent


def _facts(repo: Path, ctx: str = ".repo-ai/context") -> dict:
    return json.loads((repo / ctx / "facts.json").read_text())


def _init_none(repo: Path) -> None:
    proc = run_cli(repo, "init", "--agent", "none", "-q")
    assert proc.returncode == 0, proc.stderr


# -- manifests --------------------------------------------------------------
def test_makefile_targets_become_commands(pyweb: Path):
    _init_none(pyweb)
    commands = _facts(pyweb)["commands"]
    assert "make test" in commands["test"]
    assert "make lint" in commands["lint"]


def test_nested_requirements_are_parsed(pyweb: Path):
    _init_none(pyweb)
    deps = {(d["name"], d["manifest"]) for d in _facts(pyweb)["dependencies"]}
    assert ("pytest", "requirements/dev.txt") in deps
    assert ("ruff", "requirements/dev.txt") in deps


def test_csproj_is_parsed(tmp_path: Path):
    repo = make_repo(tmp_path, "dotnetapi")
    _init_none(repo)
    facts = _facts(repo)
    deps = {d["name"]: d for d in facts["dependencies"]}
    assert deps["Dapper"]["version"] == "2.1.35" and deps["Dapper"]["manager"] == "nuget"
    assert deps["xunit"]["scope"] == "test"
    assert any("dotnet test" in c for c in facts["commands"]["test"])
    assert any(r["path_pattern"] == "/orders/{id}" for r in facts["routes"])


def test_maven_wrapper_only_when_present(tmp_path: Path):
    commands: dict[str, list[str]] = {}
    parse_pom("pom.xml", "<project/>", commands, root=tmp_path)
    assert commands["test"] == ["mvn test"]
    (tmp_path / "mvnw").write_text("#!/bin/sh\n")
    commands = {}
    parse_pom("pom.xml", "<project/>", commands, root=tmp_path)
    assert commands["test"] == ["./mvnw test"]


def test_parse_manifest_dispatch_handles_makefile(tmp_path: Path):
    commands: dict[str, list[str]] = {}
    parse_manifest(tmp_path, "services/api/Makefile", "test:\n\tgo test ./...\n", commands)
    assert commands["test"] == ["make -C services/api test"]


# -- conventions / docs ---------------------------------------------------------
def test_generated_paths_listed_in_conventions(tsmono: Path):
    _init_none(tsmono)
    text = (tsmono / ".repo-ai" / "context" / "CONVENTIONS.md").read_text()
    section = text.split("## Do not edit", 1)[1]
    assert "packages/ui/src/generated/" in section
    assert "_None detected._" not in section


def test_recent_hotspots_section_is_populated(pyweb: Path):
    _init_none(pyweb)
    text = (pyweb / ".repo-ai" / "context" / "HOTSPOTS.md").read_text()
    recent = text.split("## Recently changed", 1)[1]
    assert "- `" in recent


def test_status_exit_codes(pyweb: Path):
    assert run_cli(pyweb, "status").returncode == 1  # not initialised
    _init_none(pyweb)
    assert run_cli(pyweb, "status").returncode == 0
    (pyweb / "app" / "new_module.py").write_text("X = 1\n")
    assert run_cli(pyweb, "status").returncode == 2
    assert run_cli(pyweb, "status", "--brief").returncode == 0


# -- incremental correctness ------------------------------------------------------
def _comparable(repo: Path) -> dict[str, str]:
    ctx = repo / ".repo-ai" / "context"
    return {p.name: TS.sub("<ts>", p.read_text()) for p in sorted(ctx.iterdir()) if p.is_file()}


def test_incremental_update_matches_fresh_rebuild(pyweb: Path):
    _init_none(pyweb)
    (pyweb / "app" / "billing" / "invoices.py").write_text(
        '"""Invoice rendering."""\nfrom app.billing.charges import charge_card\n\n'
        "def render_invoice(charge_id: str) -> str:\n    return charge_id\n")
    (pyweb / "app" / "billing" / "refunds.py").unlink()
    (pyweb / "app" / "billing" / "charges.py").write_text(
        (pyweb / "app" / "billing" / "charges.py").read_text().replace(
            "from app.billing.refunds import RefundPolicy\n", ""))
    commit_all(pyweb, "billing changes")
    assert run_cli(pyweb, "update", "-q").returncode == 0
    incremental = _comparable(pyweb)
    assert run_cli(pyweb, "rebuild", "-q").returncode == 0
    fresh = _comparable(pyweb)
    for name in fresh:
        assert incremental[name] == fresh[name], f"{name} differs between update and rebuild"


def test_deleted_file_leaves_no_stale_import_edges(pyweb: Path):
    _init_none(pyweb)
    (pyweb / "app" / "billing" / "refunds.py").unlink()
    assert run_cli(pyweb, "update", "-q").returncode == 0
    index = open_index(pyweb / ".repo-ai" / "state")
    try:
        assert index.importers_of("app/billing/refunds.py") == []
        stale = index.conn.execute(
            "SELECT COUNT(*) AS n FROM imports WHERE resolved_path='app/billing/refunds.py'").fetchone()
        assert stale["n"] == 0
    finally:
        index.close()


def test_new_file_receives_existing_importers(pyweb: Path):
    (pyweb / "app" / "api" / "audit.py").write_text("from app.billing.ledger import post\n")
    commit_all(pyweb, "audit imports a module that does not exist yet")
    _init_none(pyweb)
    (pyweb / "app" / "billing" / "ledger.py").write_text("def post() -> None:\n    pass\n")
    assert run_cli(pyweb, "update", "-q").returncode == 0
    index = open_index(pyweb / ".repo-ai" / "state")
    try:
        assert "app/api/audit.py" in index.importers_of("app/billing/ledger.py")
    finally:
        index.close()


def test_python_submodule_imports_resolve(pyweb: Path):
    _init_none(pyweb)
    proc = run_cli(pyweb, "related", "app/api/users.py", "--format", "json")
    assert "app/main.py" in json.loads(proc.stdout)["imported_by"]
    ext = {r["name"] for r in []}
    deps_md = (pyweb / ".repo-ai" / "context" / "DEPENDENCIES.md").read_text()
    assert "`app`" not in deps_md, "first-party package misreported as external"
    del ext


def test_tsconfig_path_aliases_resolve(tsmono: Path):
    _init_none(tsmono)
    proc = run_cli(tsmono, "related", "packages/core/src/cart.ts", "--format", "json")
    importers = json.loads(proc.stdout)["imported_by"]
    assert "packages/ui/src/CartSummary.tsx" in importers
    assert "packages/api/src/routes/checkout.ts" in importers


def test_schema_v4_index_is_migrated_not_wiped(pyweb: Path):
    _init_none(pyweb)
    db = pyweb / ".repo-ai" / "state" / "index.db"
    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
    conn.execute("DROP TABLE test_links")
    conn.commit()
    files_before = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    index = open_index(db.parent)
    try:
        assert index.get_meta("schema_version") == str(SCHEMA_VERSION)
        assert index.get_meta("needs_reanalysis") == "1"
        assert index.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == files_before
    finally:
        index.close()
    assert run_cli(pyweb, "update", "-q").returncode == 0
    index = open_index(db.parent)
    try:
        assert index.get_meta("needs_reanalysis") == "0"
        assert index.stats()["test_links"] > 0
    finally:
        index.close()


def test_newer_schema_is_refused_with_message(pyweb: Path):
    _init_none(pyweb)
    conn = sqlite3.connect(pyweb / ".repo-ai" / "state" / "index.db")
    conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    proc = run_cli(pyweb, "context", "login validation")
    assert proc.returncode != 0
    assert "newer than this repo-ai" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_v04_layout_is_detected_and_kept(pyweb: Path):
    assert run_cli(pyweb, "init").returncode == 0
    cfg = load_config(pyweb)
    layout = resolve_layout(pyweb, cfg)
    assert layout.kind == "legacy" and layout.context_rel == ".bob/context"


def test_v04_gitignore_section_is_migrated_and_removed(pyweb: Path):
    (pyweb / ".gitignore").write_text("node_modules/\n\n# repo-ai\n.bob/context/index.db\n"
                                      ".bob/context/index.db-wal\n.bob/context/index.db-shm\n"
                                      ".bob/context/.dirty\n")
    assert run_cli(pyweb, "init").returncode == 0
    text = (pyweb / ".gitignore").read_text()
    assert "# repo-ai\n" not in text and text.count(".bob/context/index.db\n") == 1
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert (pyweb / ".gitignore").read_text() == "node_modules/\n"


# -- retrieval --------------------------------------------------------------------
def _json_context(repo: Path, prompt: str, *extra: str) -> dict:
    proc = run_cli(repo, "context", prompt, "--format", "json", *extra)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_stack_trace_frames_rank_first_with_line_range(pyweb: Path):
    _init_none(pyweb)
    trace = ('Traceback (most recent call last):\n  File "app/billing/charges.py", line 10, '
             'in charge_card\nValueError: amount must be positive')
    data = _json_context(pyweb, trace)
    top = data["results"][0]
    assert top["path"] == "app/billing/charges.py"
    assert any(r["start"] <= 10 <= r["end"] for r in top["ranges"])
    assert data["confidence"] == "high"


def test_symbol_query_gives_exact_line_ranges(pyweb: Path):
    _init_none(pyweb)
    data = _json_context(pyweb, "change validate_credentials to reject empty passwords")
    hit = next(r for r in data["results"] if r["path"] == "app/auth/login.py")
    assert any("validate_credentials" in r["label"] for r in hit["ranges"])
    assert "symbol_exact" in hit["breakdown"]


def test_irrelevant_prompt_returns_nothing(pyweb: Path):
    _init_none(pyweb)
    data = _json_context(pyweb, "write me a haiku about autumn leaves")
    assert data["results"] == [] and data["confidence"] == "none"


def test_scope_diff_restricts_results(pyweb: Path):
    _init_none(pyweb)
    target = pyweb / "app" / "billing" / "refunds.py"
    target.write_text(target.read_text() + "\n# refund window tweak\n")
    data = _json_context(pyweb, "refund policy window", "--scope", "diff")
    paths = [r["path"] for r in data["results"]]
    assert paths and paths[0] == "app/billing/refunds.py"
    assert run_cli(pyweb, "context", "x", "--scope", "bogus").returncode != 0


def test_impact_report(pyweb: Path):
    _init_none(pyweb)
    data = json.loads(run_cli(pyweb, "impact", "app/auth/tokens.py", "--format", "json").stdout)
    importers = {i["path"] for i in data["importers"]}
    assert {"app/auth/login.py", "app/auth/middleware.py"} <= importers
    assert "app/api/users.py" in importers  # transitive, via login.py
    tests = {t["path"] for t in data["tests"]}
    assert "tests/test_tokens.py" in tests
    assert "pytest tests/test_tokens.py" in data["suggested_commands"]
    assert any("static import graph" in u for u in data["uncertainty"])
    sym = json.loads(run_cli(pyweb, "impact", "charge_card", "--format", "json").stdout)
    assert sym["targets"] == ["app/billing/charges.py"]


def test_impact_changed_uses_working_tree(pyweb: Path):
    _init_none(pyweb)
    (pyweb / "app" / "billing" / "charges.py").write_text(
        (pyweb / "app" / "billing" / "charges.py").read_text() + "\n# tweak\n")
    data = json.loads(run_cli(pyweb, "impact", "--changed", "--format", "json").stdout)
    assert data["targets"] == ["app/billing/charges.py"]
    assert "tests/test_charges.py" in {t["path"] for t in data["tests"]}


def test_explain_prints_breakdown(pyweb: Path):
    _init_none(pyweb)
    proc = run_cli(pyweb, "explain", "JWT tokens expire too early")
    assert "app/auth/tokens.py" in proc.stdout and "lexical=" in proc.stdout


def test_query_cache_invalidates_on_change(pyweb: Path):
    _init_none(pyweb)
    first = _json_context(pyweb, "loyalty points balance calculation")
    assert first["results"] == []
    (pyweb / "app" / "billing" / "loyalty.py").write_text(
        '"""Loyalty points."""\n\ndef points_balance(user_id: int) -> int:\n'
        '    """Loyalty points balance calculation."""\n    return 0\n')
    assert run_cli(pyweb, "update", "-q").returncode == 0
    second = _json_context(pyweb, "loyalty points balance calculation")
    assert second["results"] and second["results"][0]["path"] == "app/billing/loyalty.py"


@pytest.mark.parametrize("hostile", ['" OR 1=1 --', "NEAR(a b)", "files:*", "^start",
                                     "a AND NOT b", '"unterminated', "(((", "*"])
def test_fts_query_injection_is_inert(pyweb: Path, hostile: str):
    _init_none(pyweb)
    for cmd in (["search", hostile], ["context", hostile, "--format", "json"]):
        proc = run_cli(pyweb, *cmd)
        assert proc.returncode == 0, (cmd, proc.stderr)
    assert fts_escape(hostile).count('"') % 2 == 0


def test_monorepo_components(tsmono: Path):
    _init_none(tsmono)
    roots = {c["root"] for c in _facts(tsmono)["components"]}
    assert {"packages/core", "packages/api", "packages/ui"} <= roots


# -- packaging hygiene ------------------------------------------------------------
def test_python310_dependency_is_declared():
    text = (ROOT / "pyproject.toml").read_text()
    assert "tomli" in text and "python_version < '3.11'" in text
    assert "embeddings" not in text, "do not advertise unimplemented features"


def test_license_and_docs_exist():
    assert "MIT License" in (ROOT / "LICENSE").read_text()
    for doc in ("ARCHITECTURE.md", "CLAUDE_CODE.md", "LEARNING.md", "RETRIEVAL.md",
                "COMPATIBILITY.md", "CONFIGURATION.md"):
        assert (ROOT / "docs" / doc).is_file(), doc


def test_retired_config_keys_are_reported_not_fatal(pyweb: Path):
    (pyweb / ".repo-ai.toml").write_text("embeddings = true\nlearning_policy = \"yolo\"\n")
    cfg = load_config(pyweb)
    assert "embeddings" in cfg.extra["_retired_config_keys"]
    assert "learning_policy" in cfg.extra["_bad_config_keys"]
    assert cfg.learning_policy == "suggest"


def test_python_version_floor():
    assert sys.version_info >= (3, 10)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_v04_gitignore_migration_is_not_drift(pyweb: Path, eol: str):
    text = "node_modules/\n\n# repo-ai\n.bob/context/index.db\n.bob/context/.dirty\n"
    (pyweb / ".gitignore").write_bytes(text.replace("\n", eol).encode())
    commit_all(pyweb, "v0.4-style gitignore")
    assert run_cli(pyweb, "init", "-q").returncode == 0  # Bob-only, as in v0.4
    status = run_cli(pyweb, "status", "--json")
    data = json.loads(status.stdout)
    assert ".gitignore" not in data["drift"], data["drift"]


def test_invalid_config_toml_is_reported_not_silently_ignored(pyweb: Path):
    (pyweb / ".repo-ai.toml").write_text('claude_cmd = "C:\\Users\\x\\python.exe"\n')
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    out = run_cli(pyweb, "doctor", "--agent", "claude", "--json").stdout
    assert "not valid TOML" in out
