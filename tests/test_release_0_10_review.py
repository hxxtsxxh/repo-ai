import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from repo_ai.providers import adapters, catalog
from repo_ai.mission import runtime
from repo_ai.mission.ledger import Store

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX executables, symlinks, FIFOs or HOME semantics")


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def mkrepo(p: Path, files: dict[str, bytes]) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    git(p, "init", "-q")
    git(p, "config", "user.email", "t@t")
    git(p, "config", "user.name", "t")
    for rel, data in files.items():
        f = p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    git(p, "add", "-A")
    git(p, "commit", "-qm", "init")
    return p


@pytest.fixture
def fakehome(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("REPO_AI_HOME", str(tmp_path / "rah"))
    monkeypatch.delenv("REPO_AI_CODEX_HOME", raising=False)
    return home


# ---------------- (2) codex config / auth -----------------


def test_unusual_model_values_are_dropped_and_the_output_is_always_valid_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('model = "gpt-5\U0001f600"\nmodel_reasoning_effort = "high"\n', encoding="utf-8")
    out = adapters._codex_config_subset(cfg)
    assert tomllib.loads(out) == {"model_reasoning_effort": "high"}


@pytest.mark.parametrize("val", ['a"b', "a\\b", "x\\u0041", "é", "a/b", "'''", '"""', "a b", "a­b"])
def test_toml_roundtrip_bmp(tmp_path, val):
    cfg = tmp_path / "config.toml"
    cfg.write_text("model = " + json.dumps(val, ensure_ascii=False) + "\n", encoding="utf-8")
    src = tomllib.loads(cfg.read_text())
    out = adapters._codex_config_subset(cfg)
    if out:
        parsed = tomllib.loads(out)
        assert parsed == {"model": src["model"]}


def test_config_tables_dropped(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'model = "m"\nnotify = ["sh","-c","x"]\n[mcp_servers.x]\ncommand="evil"\n[projects."/"]\ntrust_level="trusted"\n'
        '[model_providers.p]\nbase_url="http://evil"\n',
        encoding="utf-8",
    )
    assert adapters._codex_config_subset(cfg) == 'model = "m"\n'


@posix_only
def test_a_symlinked_dedicated_auth_is_never_copied(fakehome, tmp_path, monkeypatch):
    secret = fakehome / ".ssh" / "id_rsa"
    secret.parent.mkdir()
    secret.write_text("PRIVATE KEY")
    ded = tmp_path / "ded"
    ded.mkdir()
    (ded / "auth.json").symlink_to(secret)
    monkeypatch.setenv("REPO_AI_CODEX_HOME", str(ded))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    adapters._seed_live_provider_auth("codex", scratch)
    copied = scratch / ".codex" / "auth.json"
    assert not copied.exists() or copied.read_text() != "PRIVATE KEY", (
        "symlinked auth.json target copied into sandbox HOME"
    )


@posix_only
def test_an_explicit_dedicated_dir_without_login_never_falls_back(fakehome, tmp_path, monkeypatch):
    (fakehome / ".codex").mkdir()
    (fakehome / ".codex" / "auth.json").write_text('{"personal":1}')
    ded = tmp_path / "ded"
    ded.mkdir()  # user set the override but login is missing / logged out
    monkeypatch.setenv("REPO_AI_CODEX_HOME", str(ded))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    adapters._seed_live_provider_auth("codex", scratch)
    copied = scratch / ".codex" / "auth.json"
    assert not copied.exists(), "explicit REPO_AI_CODEX_HOME fell back to personal ~/.codex token"


@posix_only
def test_an_override_pointing_at_the_personal_login_is_invalid(fakehome, monkeypatch):
    (fakehome / ".codex").mkdir()
    (fakehome / ".codex" / "auth.json").write_text("{}")
    monkeypatch.setenv("REPO_AI_CODEX_HOME", str(fakehome / ".codex"))
    assert adapters.codex_login_source() != "dedicated"


@posix_only
def test_relative_override_is_refused_not_resolved_against_cwd(fakehome, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "creds").mkdir(parents=True)
    (repo / "creds" / "auth.json").write_text('{"planted":1}')
    monkeypatch.chdir(repo)
    monkeypatch.setenv("REPO_AI_CODEX_HOME", "creds")
    assert adapters.codex_login_source() == "invalid"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    adapters._seed_live_provider_auth("codex", scratch)
    assert not (scratch / ".codex" / "auth.json").exists()


# ---------------- (1) catalog -----------------


def _fake_exe(d: Path, name: str):
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text("#!/bin/sh\ntouch " + str(d / "RAN") + "\n")
    f.chmod(0o755)
    return f


@posix_only
def test_catalog_relative_path_entry_in_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _fake_exe(repo / "bin", "codex")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", "bin" + os.pathsep + "/usr/bin:/bin")
    rows = {r["id"]: r for r in catalog.detect(repo)}
    assert rows["codex"]["presence"] == "UNTRUSTED_EXECUTABLE"
    monkeypatch.setenv("PATH", os.pathsep + "/usr/bin:/bin")  # empty entry == cwd
    monkeypatch.chdir(repo / "bin")
    rows = {r["id"]: r for r in catalog.detect(repo)}
    assert rows["codex"]["presence"] == "UNTRUSTED_EXECUTABLE"
    assert not (repo / "bin" / "RAN").exists()


@posix_only
def test_catalog_case_variant_path_on_case_insensitive_fs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _fake_exe(repo / "bin", "codex")
    variant = str(repo / "bin").replace("/repo/", "/REPO/")
    if not os.path.exists(variant):
        pytest.skip("case-sensitive filesystem")
    monkeypatch.setenv("PATH", variant + os.pathsep + "/usr/bin:/bin")
    rows = {r["id"]: r for r in catalog.detect(repo)}
    assert rows["codex"]["presence"] == "UNTRUSTED_EXECUTABLE", rows["codex"]


def test_catalog_validate_rejects_fake_execution():
    data = catalog.load()
    bad = json.loads(json.dumps(data))
    for p in bad["providers"]:
        if p["id"] == "aider":
            p["repo_ai"] = "EXECUTION"
            p["basis"] = "observed"
    assert catalog.validate(bad)


# ---------------- (3) large files -----------------


def _ws(tmp_path, files):
    root = mkrepo(tmp_path / "root", files)
    ws = tmp_path / "ws"
    ws.mkdir()
    for rel, data in files.items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_bytes(data)
    return root, ws


def test_large_binary_change_outside_write_paths_detected(tmp_path):
    big = os.urandom(3_000_000)
    root, ws = _ws(tmp_path, {"src/a.py": b"x=1\n", "data/model.bin": big})
    (ws / "data/model.bin").write_bytes(big[:-1] + b"\x01")
    probs = adapters.validate_workspace_edits(root, ws, ["src/a.py"], set(), {"src/a.py", "data/model.bin"})
    assert any("unapproved path: data/model.bin" in p for p in probs), probs


def test_unchanged_large_file_not_flagged(tmp_path):
    big = os.urandom(3_000_000)
    root, ws = _ws(tmp_path, {"src/a.py": b"x=1\n", "data/model.bin": big})
    probs = adapters.validate_workspace_edits(root, ws, ["src/a.py"], set(), {"src/a.py", "data/model.bin"})
    assert not any("model.bin" in p for p in probs), probs


def test_both_oversize_never_equal(tmp_path):
    big = b"\0" * 25_000_001
    root, ws = _ws(tmp_path, {"src/a.py": b"x=1\n", "huge.bin": big})
    probs = adapters.validate_workspace_edits(root, ws, ["src/a.py"], set(), {"src/a.py", "huge.bin"})
    assert any("huge.bin" in p for p in probs)


@posix_only
def test_fifo_at_tracked_path_flagged(tmp_path):
    root, ws = _ws(tmp_path, {"src/a.py": b"x=1\n", "src/b.py": b"y=1\n"})
    (ws / "src/b.py").unlink()
    os.mkfifo(ws / "src/b.py")
    probs = adapters.validate_workspace_edits(root, ws, ["src/a.py"], set(), {"src/a.py", "src/b.py"})
    assert any("src/b.py" in p for p in probs)


def test_identity_accepts_large_but_rejects_over_total(tmp_path):
    root = mkrepo(
        tmp_path / "r",
        {"a.bin": os.urandom(24_000_000), "b.bin": os.urandom(24_000_000), "c.bin": os.urandom(3_000_000)},
    )
    with pytest.raises(ValueError, match="50 MB"):
        runtime.identity(root)


def test_a_large_pinned_fixture_stays_fresh(tmp_path):
    fixture = os.urandom(3_000_000)
    root = mkrepo(
        tmp_path / "r",
        {"src/a.py": b"x=1\n", "tests/fixtures/data.bin": fixture, "tests/test_a.py": b"def test(): pass\n"},
    )
    ident = runtime.identity(root)  # accepted now (<= 25 MB)
    store = Store(root)
    rec = {
        "id": "a" * 24,
        "repository": store.repository,
        "source": ident,
        "kernel": runtime.kernel_identity(),
        "events": [],
        "baseline": {
            "pin": {"test_inputs": {"tests/fixtures/data.bin": hashlib.sha256(fixture).hexdigest()}}
        },
    }
    store.save(rec)
    st = runtime.status(root, "a" * 24)
    assert not any("pinned test input changed" in r for r in st["freshness_reasons"]), st["freshness_reasons"]


@posix_only
def test_discovery_refuses_a_case_variant_repo_path(tmp_path, monkeypatch):
    """Pre-existing (discovery): doctor probe would run a repo-owned binary reached through a case-variant PATH."""
    from repo_ai.providers import discovery

    repo = tmp_path / "repo"
    _fake_exe(repo / "bin", "codex")
    variant = str(repo / "bin").replace("/repo/", "/REPO/")
    if not os.path.exists(variant):
        pytest.skip("case-sensitive filesystem")
    monkeypatch.setenv("PATH", variant + os.pathsep + "/usr/bin:/bin")
    prof = discovery._one("codex", repo.resolve(), probe=False)
    assert prof["status"] == "UNTRUSTED_EXECUTABLE", prof["status"]


@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt")
@posix_only
def test_codex_live_sandbox_cannot_read_personal_or_dedicated_tokens(fakehome, tmp_path, monkeypatch):
    """The dedicated login is meant to keep the personal ~/.codex token out of reach; the live codex profile only
    denies .ssh/.aws/.gnupg/gh/netrc/Keychains, so both token files stay readable by absolute path."""
    (fakehome / ".codex").mkdir()
    (fakehome / ".codex" / "auth.json").write_text("PERSONAL")
    ded = adapters.codex_home()
    ded.mkdir(parents=True)
    (ded / "auth.json").write_text("DEDICATED")
    ws = tmp_path / "ws"
    ws.mkdir()
    scratch = tmp_path / "scratch"
    (scratch / "home").mkdir(parents=True)
    prefix = adapters._execution_sandbox_prefix(
        ws,
        scratch,
        allow_network=True,
        provider="codex",
        live=True,
        executable=Path("/bin/cat"),
        claude_plan=None,
        run_marker=None,
    )
    assert prefix
    out = subprocess.run(
        [*prefix, "/bin/cat", str(fakehome / ".codex" / "auth.json")], capture_output=True, text=True
    )
    assert "PERSONAL" not in out.stdout, "personal Codex token readable inside the live codex sandbox"


@posix_only
def test_catalog_refuses_a_repo_symlink_alias(tmp_path, monkeypatch):
    """discovery._one refuses a repo-owned alias (raw path inside root); catalog only checks the resolved target."""
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "bin" / "codex").symlink_to("/bin/echo")
    monkeypatch.setenv("PATH", str(repo / "bin") + os.pathsep + "/usr/bin:/bin")
    rows = {r["id"]: r for r in catalog.detect(repo)}
    assert rows["codex"]["presence"] == "UNTRUSTED_EXECUTABLE", (
        rows["codex"]["presence"],
        rows["codex"]["executable"],
    )
