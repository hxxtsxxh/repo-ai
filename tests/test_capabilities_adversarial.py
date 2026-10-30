# ruff: noqa: F811  (pytest fixtures imported from test_capabilities are parameters here)
"""Found by two adversarial reviews of the capability adapter and the agent menu, then fixed.

Each test keeps the attack form that used to pass: a finding hidden from changed-line attribution,
a scan reported clean although ruff did not lint everything, evidence that stayed fresh for a different
change or binary, approval from a non-interactive shell, and trust lifted by repository files or long
task text.
"""

from __future__ import annotations

import json
import subprocess
import tempfile

import pytest

from repo_ai import capabilities as caps
from repo_ai import capdiscovery as cd
from test_capabilities import POSIX, _approve, _git, _select, fake_ruff, home, repo  # noqa: F401

SHELL = "def r(c):\n    return subprocess.run(c, shell=True)\n"


def _ran(repo, tmp_path, **kw):
    return caps.run(repo, tmp_path / "state", "adapter.ruff-security", **kw)


def _commit(repo, rel, text):
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, "utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-qm", "base")


# ---------------------------------------------------------------- attribution
@POSIX
@pytest.mark.parametrize("trap", ["plus", "gitattributes", "color", "inter-hunk"])
def test_added_lines_cannot_be_hidden_from_attribution(repo, home, fake_ruff, tmp_path, trap):
    """An added line starting with `++`, `*.py -diff`, and colour or inter-hunk context forced by repository
    config each made a new finding count as pre-existing."""
    exe, _ = fake_ruff
    _approve(repo, exe)
    base = "x = 1\ny = 2\nz = 3\nw = 4\nv = 5\n"
    _commit(repo, "app/a.py", base)
    if trap == "gitattributes":
        _commit(repo, ".gitattributes", "*.py -diff\n")
    if trap == "color":
        _git(repo, "config", "color.diff", "always")
    if trap == "inter-hunk":
        _git(repo, "config", "diff.interHunkContext", "5")
    body = "x = 1\ns = '''\n++ docs\n'''\ny = 2\nz = 3\nw = 4\nv = 5\n" if trap == "plus" else base
    (repo / "app" / "a.py").write_text(body + SHELL, "utf-8")
    res = _ran(repo, tmp_path, files=["app/a.py"])
    assert res["status"] == "ran" and [f["new"] for f in res["findings"]] == [True], res


@POSIX
def test_a_file_named_like_a_pathspec_is_attributed_literally(repo, home, fake_ruff, tmp_path):
    exe, _ = fake_ruff
    _approve(repo, exe)
    (repo / ":(exclude)evil.py").write_text("x = 1\nyaml.load(t)\n", "utf-8")
    res = _ran(repo, tmp_path, files=[":(exclude)evil.py", "app/old.py"])
    assert {(f["path"], f["new"]) for f in res["findings"] if f["rule"] == "S506"} == {(":(exclude)evil.py", True)}


# ---------------------------------------------------------------- fail closed
@POSIX
@pytest.mark.parametrize("mode,error", [("unselected", "did not select"), ("latin", "not UTF-8")])
def test_a_scan_that_did_not_lint_everything_is_an_error(repo, home, fake_ruff, tmp_path, mode, error):
    exe, mode_file = fake_ruff
    _approve(repo, exe)
    if mode == "latin":
        (repo / "app" / "new.py").write_bytes("# -*- coding: latin-1 -*-\ns = 'caf\xe9'\n".encode("latin-1"))
    else:
        mode_file.write_text("unselected")
    res = _ran(repo, tmp_path)
    assert res["status"] == "error" and error in res["error"]
    assert caps.evidence(repo, tmp_path / "state")["status"] == "none"


@POSIX
def test_too_many_results_is_an_error_not_a_count(repo, home, fake_ruff, tmp_path, monkeypatch):
    exe, _ = fake_ruff
    _approve(repo, exe)
    monkeypatch.setattr(caps, "MAX_RESULTS", 1)
    assert "not truncated" in _ran(repo, tmp_path)["error"]


# ---------------------------------------------------------------- evidence
@POSIX
def test_skipped_or_odd_names_never_leave_fresh_evidence(repo, home, fake_ruff, tmp_path):
    exe, _ = fake_ruff
    _approve(repo, exe)
    (repo / "-evil.py").write_text("yaml.load(t)\n", "utf-8")
    res = _ran(repo, tmp_path)
    assert "-evil.py" in res["files"]  # a leading dash is a file name after `--`
    assert caps.evidence(repo, tmp_path / "state")["status"] == "fresh"
    outside = tmp_path / "outside.py"
    outside.write_text("yaml.load(t)\n", "utf-8")
    (repo / "app" / "link.py").symlink_to(outside)
    ev = caps.evidence(repo, tmp_path / "state")
    assert ev["status"] == "incomplete" and "app/link.py" in ev["skipped"]
    (repo / "app" / "link.py").unlink()
    (repo / ".claude" / "hooks").mkdir(parents=True)
    (repo / ".claude" / "hooks" / "pre.py").write_text("x = 1\n", "utf-8")  # hooks there run: scanned too
    assert caps.evidence(repo, tmp_path / "state")["status"] == "stale"


@POSIX
def test_evidence_is_bound_to_the_current_approval(repo, home, fake_ruff, tmp_path):
    exe, _ = fake_ruff
    _approve(repo, exe)
    _ran(repo, tmp_path)
    assert caps.evidence(repo, tmp_path / "state")["status"] == "fresh"
    with open(exe, "a") as fh:
        fh.write("# changed\n")
    assert caps.evidence(repo, tmp_path / "state")["status"] == "stale"
    _approve(repo, exe)
    assert caps.evidence(repo, tmp_path / "state")["status"] == "stale"  # another binary produced it
    _ran(repo, tmp_path)
    caps.revoke(repo, ["adapter.ruff-security"])
    assert caps.evidence(repo, tmp_path / "state")["status"] == "stale"


@POSIX
def test_staged_content_that_differs_from_the_scanned_tree_is_not_fresh(repo, home, fake_ruff, tmp_path):
    exe, _ = fake_ruff
    _approve(repo, exe)
    (repo / "app" / "new.py").write_text(SHELL, "utf-8")
    _git(repo, "add", "app/new.py")
    (repo / "app" / "new.py").write_text("x = 1\n", "utf-8")
    _ran(repo, tmp_path)
    assert caps.evidence(repo, tmp_path / "state")["status"] == "incomplete"


# ---------------------------------------------------------------- approval and placement
@pytest.mark.parametrize("env", [{"CLAUDECODE": ""}, {"CLAUDE_CODE_SSE_PORT": "1"}, {"GITHUB_ACTIONS": "true"}])
def test_approve_is_refused_for_any_agent_marker_even_empty(repo, home, fake_ruff, env):
    exe, _ = fake_ruff
    prep = caps.prepare(repo, "adapter.ruff-security", str(exe))
    with pytest.raises(caps.CapabilityError, match="agent shell"):
        caps.approve(repo, "adapter.ruff-security", prep["sha256"][:16], str(exe), env=env)


def test_approve_is_refused_without_a_terminal(repo, home, fake_ruff):
    exe, _ = fake_ruff
    prep = caps.prepare(repo, "adapter.ruff-security", str(exe))
    with pytest.raises(caps.CapabilityError, match="not a TTY"):
        caps.approve(repo, "adapter.ruff-security", prep["sha256"][:16], str(exe), env={}, interactive=False)


@POSIX
def test_temporary_files_and_records_never_land_in_the_repository(repo, home, fake_ruff, tmp_path, monkeypatch):
    exe, _ = fake_ruff
    monkeypatch.setenv("TMPDIR", str(repo))
    monkeypatch.setattr(tempfile, "tempdir", None)
    before = sorted(p.name for p in repo.iterdir())
    _approve(repo, exe)
    _ran(repo, tmp_path)
    assert sorted(p.name for p in repo.iterdir()) == before
    monkeypatch.setenv("REPO_AI_HOME", str(repo / ".home"))
    with pytest.raises(caps.CapabilityError, match="inside this repository"):
        _approve(repo, exe)


def test_a_committed_index_is_not_this_machines_index(repo):
    idx = repo / ".repo-ai" / "state" / "index.db"
    idx.parent.mkdir(parents=True)
    idx.write_bytes(b"")
    assert caps.index_ready(repo, idx)
    _git(repo, "add", "-f", str(idx.relative_to(repo)))
    assert not caps.index_ready(repo, idx)


# ---------------------------------------------------------------- the menu and its text
def test_next_steps_carry_no_command_an_agent_could_run():
    for c in caps.load_manifest()["capabilities"]:
        if c["kind"] == "builtin":
            continue  # built-ins are never unapproved or uninstalled
        for reason in ("not_approved", "binding_changed", "not_installed", "no_adapter", "not_managed_by_repo_ai"):
            step = caps._next_step(c, {"status": False, "reason": reason})
            assert not any(t in step for t in ("capabilities prepare", "capabilities approve", "--online",
                                               "--sha256")), (c["id"], step)


def test_context_task_is_an_operand_after_the_separator(repo, home, monkeypatch):
    seen = {}

    def fake(cmd, **k):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "{}", "")
    monkeypatch.setattr(caps.subprocess, "run", fake)
    res = caps._run_builtin(repo, caps.by_id(caps.load_manifest())["repo-ai.context"], "-C /etc --evil")
    assert seen["cmd"][-2:] == ["--", "-C /etc --evil"] and "-C /etc --evil" not in json.dumps(res)


def test_select_rejects_a_missing_base(repo, home, capsys):
    assert _select(repo, capsys, "what skills are installed", "none", "cd1:" + "0" * 32, "--base", "HEAD~99")[0] == 2


def test_a_constraint_past_the_analysed_text_is_still_read():
    task = "fix the SQL injection in the login handler. " + "pad " * 520 + "use only built in tools, no third party."
    assert len(task) > cd.MAX_TASK_CHARS
    assert "no-third-party" in cd.discover(task, {"languages": ["Python"]}, [], caps.load_manifest())["constraints"]


def test_all_never_brings_back_a_gated_record(repo, home, capsys):
    from test_capabilities import _menu
    menu = _menu(repo, capsys, "rename a variable", "--files", "main.go", "--all")
    assert "adapter.ruff-security" not in {c["id"] for c in menu["candidates"]}
    assert {"id": "adapter.ruff-security", "why": "lang"} in menu["excluded"]


# ---------------------------------------------------------------- explicit constraints are authoritative
def test_recommend_enforces_an_explicit_deny_and_rejects_an_unknown_one(repo, home, capsys):
    from repo_ai import cli
    args = ["capabilities", "recommend", "--task", "are our pinned dependencies known to be vulnerable?",
            "--files", "requirements.txt", "-C", str(repo), "--json"]
    assert cli.main(args) == 0
    plain = json.loads(capsys.readouterr().out)
    assert cli.main([*args, "--deny", "no-network"]) == 0
    denied = json.loads(capsys.readouterr().out)
    assert "adapter.dependency-audit" not in {r["id"] for r in denied["recommended"]}
    assert denied["signals"]["constraints"]["explicit"] == ["no-network"]
    assert plain["signals"]["constraints"]["explicit"] == []
    assert cli.main([*args, "--deny", "no-netwrok"]) == 2  # never silently ignored


def test_the_menu_says_which_constraints_were_explicit(repo, home, capsys):
    from test_capabilities import _menu
    menu = _menu(repo, capsys, "check the lockfile for vulnerable packages, offline please", "--files",
                 "requirements.txt", "--deny", "no-exec")
    assert menu["constraints"]["explicit"] == ["no-exec"]
    assert "no-network" in menu["constraints"]["inferred"]
