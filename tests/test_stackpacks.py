"""Stack Packs: built only from the same zone, only from items several
repositories share, and never carrying paths or local sources."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import make_repo, run_cli

from repo_ai import registry, stackpacks


def _env(tmp_path: Path) -> dict[str, str]:
    return {"REPO_AI_HOME": str(tmp_path / "rh"), "XDG_CONFIG_HOME": str(tmp_path / "xdg")}


def _lock_with(repo: Path, entries: dict) -> None:
    (repo / ".repo-ai").mkdir(exist_ok=True)
    (repo / ".repo-ai" / "skills.lock.json").write_text(json.dumps({"version": 1, "skills": entries}))


PUBLIC = {"source": {"provider": "github", "owner": "anthropics", "repo": "skills",
                     "commit": "dbd4588f" + "0" * 32}, "content_hash": "ab" * 32, "status": "active",
          "stage": "promoted", "evidence": {"status": "pilot", "diff": 0.2}, "files": []}
LOCAL = {"source": {"provider": "local", "owner": "", "repo": "", "path": "/Users/me/secret-skill",
                    "commit": ""}, "content_hash": "cd" * 32, "status": "active", "files": []}


def test_packs_need_support_stay_in_zone_and_carry_no_paths(tmp_path: Path):
    env = _env(tmp_path)
    repos = [make_repo(tmp_path, "pyweb", f"svc{i}") for i in range(3)]
    for r in repos:
        assert run_cli(r, "init", "--agent", "claude", "-q", env=env).returncode == 0
    other = make_repo(tmp_path, "pyweb", "work-svc")
    assert run_cli(other, "init", "--agent", "claude", "-q", env=env).returncode == 0
    assert run_cli(other, "registry", "add", "--zone", "work", env=env).returncode == 0
    _lock_with(repos[0], {"anthropic-pdf": PUBLIC, "my-local": LOCAL})
    _lock_with(repos[1], {"anthropic-pdf": PUBLIC})
    assert run_cli(repos[0], "registry", "add", "--zone", "personal", env=env).returncode == 0
    assert run_cli(repos[0], "registry", "contribute", env=env).returncode == 0
    # one contributor is not a pack
    out = run_cli(repos[2], "registry", "add", "--zone", "personal", env=env)
    assert out.returncode == 0
    listing = run_cli(repos[2], "pack", "list", env=env)
    assert listing.returncode == 0 and "no Stack Packs" in listing.stdout
    assert run_cli(repos[1], "registry", "add", "--zone", "personal", env=env).returncode == 0
    assert run_cli(repos[1], "registry", "contribute", env=env).returncode == 0
    rows = json.loads(run_cli(repos[2], "pack", "list", "--json", env=env).stdout)
    assert len(rows) == 1 and rows[0]["repos"] == 2
    plan = json.loads(run_cli(repos[2], "pack", "plan", "--json", env=env).stdout)
    third = [i for i in plan["items"] if i["type"] == "third-party skill"]
    assert [i["item"] for i in third] == ["anthropics/skills:anthropic-pdf"]
    assert third[0]["status"] == "vet and approve" and "--approve abababab" in third[0]["next"]
    assert "nothing was changed" in plan["note"]
    # the zone file never holds the local skill or any absolute path
    zone_files = list(Path(env["REPO_AI_HOME"]).rglob("patterns.json"))
    assert len(zone_files) == 1
    text = zone_files[0].read_text()
    assert "anthropic-pdf" in text  # the check below is not vacuous
    audit = run_cli(repos[2], "registry", "audit", env=env)
    assert audit.returncode == 0, audit.stdout
    assert "secret-skill" not in text and "my-local" not in text and str(tmp_path) not in text
    # another zone sees nothing
    work = run_cli(other, "pack", "list", env=env)
    assert work.returncode == 0 and "no Stack Packs" in work.stdout
    # unregistered repositories get no packs at all
    lone = make_repo(tmp_path, "pyweb", "lone")
    assert run_cli(lone, "init", "--agent", "claude", "-q", env=env).returncode == 0
    refused = run_cli(lone, "pack", "list", env=env)
    assert refused.returncode != 0 and "registry add" in refused.stderr


def test_harmful_measured_skill_is_left_out(monkeypatch):
    base = {"stack": {"languages": ["python"], "frameworks": ["flask"], "tests": ["pytest"]},
            "rules": ["test:-"], "skills": [], "outcomes": {}}
    bad = {"name": "x", "owner": "o", "repo": "r", "commit": "a" * 40, "content_hash": "b" * 64,
           "evidence": "evaluated", "diff": -0.3}
    library = {"k": {**base, "by_repo": {"r1": {**base, "thirdparty": [bad]},
                                         "r2": {**base, "thirdparty": []}}}}
    monkeypatch.setattr(registry, "patterns", lambda zone: library)
    packs = stackpacks.build("personal")
    assert packs[0]["rules"] == [("test:-", 2)]
    assert packs[0]["thirdparty"] == []  # one repo, measured harm: not in the pack
