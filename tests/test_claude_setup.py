"""Setup and ownership: `repo-ai init --agent claude --smart` and friends.

The invariants: human content is never modified, nothing is duplicated on
re-run, dry runs write nothing, uninstall removes exactly what repo-ai owns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_repo, run_cli, snapshot

BEGIN = "<!-- BEGIN repo-ai:claude -->"
HUMAN_CLAUDE = "# Team rules\n\nAlways run `make lint` before pushing.\nUse tabs in Makefiles.\n"


def _init(repo: Path, *extra: str) -> None:
    proc = run_cli(repo, "init", "--agent", "claude", "--smart", "-q", *extra)
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_fresh_repo_gets_full_claude_setup(pyweb: Path):
    _init(pyweb)
    claude = pyweb / ".claude"
    assert BEGIN in (pyweb / "CLAUDE.md").read_text()
    for skill in ("repo-orient", "repo-locate", "repo-impact", "repo-verify", "repo-debug",
                  "repo-review", "repo-learn"):
        assert (claude / "skills" / skill / "SKILL.md").is_file(), skill
    # a new install is the "core" set: no subagents until asked for (see the next test)
    assert not (claude / "agents").exists()
    assert 'feature_set = "core"' in (pyweb / ".repo-ai" / "config.toml").read_text()
    settings = json.loads((claude / "settings.json").read_text())
    for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
        assert event in settings["hooks"], event
    assert (claude / "hooks" / "repo-ai.sh").is_file()
    assert (pyweb / ".repo-ai" / "state" / "index.db").is_file()
    assert (pyweb / ".repo-ai" / "context" / "ARCHITECTURE.md").is_file()
    assert (pyweb / ".repo-ai" / "config.toml").is_file()
    assert ".repo-ai/state/" in (pyweb / ".gitignore").read_text()
    # Bob is untouched by a Claude-only init.
    assert not (pyweb / ".bob").exists()
    assert not (pyweb / "AGENTS.md").exists()


def test_full_feature_set_adds_subagents_and_core_removes_them(pyweb: Path):
    _init(pyweb, "--feature-set", "full")
    claude = pyweb / ".claude"
    for agent in ("repo-explorer", "repo-impact-analyst", "repo-verifier", "repo-security-reviewer",
                  "repo-skeptic"):
        assert (claude / "agents" / f"{agent}.md").is_file(), agent
    assert 'feature_set = "full"' in (pyweb / ".repo-ai" / "config.toml").read_text()
    _init(pyweb)  # no flag: the recorded choice stands
    assert (claude / "agents" / "repo-explorer.md").is_file()
    _init(pyweb, "--feature-set", "core")
    assert not list((claude / "agents").glob("repo-*.md")) if (claude / "agents").exists() else True


def test_an_explicit_key_beats_the_feature_set(pyweb: Path):
    _init(pyweb)
    cfg = pyweb / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text() + "write_claude_agents = true\n")
    _init(pyweb)
    assert (pyweb / ".claude" / "agents" / "repo-explorer.md").is_file()  # core, but agents asked for


def test_installs_from_before_feature_sets_keep_their_behaviour(pyweb: Path):
    _init(pyweb)
    cfg = pyweb / ".repo-ai" / "config.toml"
    # an 0.7.5-era config: no feature_set line at all
    cfg.write_text("\n".join(line for line in cfg.read_text().splitlines()
                             if not line.startswith("feature_set")) + "\n")
    _init(pyweb)
    assert (pyweb / ".claude" / "agents" / "repo-explorer.md").is_file()  # the earlier default


def test_claude_md_block_is_small_and_human_text_survives(pyweb: Path):
    (pyweb / "CLAUDE.md").write_text(HUMAN_CLAUDE)
    _init(pyweb)
    text = (pyweb / "CLAUDE.md").read_text()
    assert text.startswith(HUMAN_CLAUDE)
    block = text[text.index(BEGIN):]
    assert len(block) // 4 < 450, f"managed block too expensive: ~{len(block) // 4} tokens"


def test_reinit_is_byte_identical_fixed_point(pyweb: Path):
    (pyweb / "CLAUDE.md").write_text(HUMAN_CLAUDE)
    _init(pyweb)
    first = snapshot(pyweb)
    _init(pyweb)
    assert run_cli(pyweb, "update", "-q").returncode == 0
    second = snapshot(pyweb)
    changed = sorted(k for k in set(first) | set(second) if first.get(k) != second.get(k))
    assert not changed, f"re-init/update changed: {changed}"
    text = (pyweb / "CLAUDE.md").read_text()
    assert text.count(BEGIN) == 1
    settings = json.loads((pyweb / ".claude" / "settings.json").read_text())
    for event, entries in settings["hooks"].items():
        ours = [e for e in entries if "repo-ai.sh" in json.dumps(e)]
        # PostToolUse: edits, known Bash commands, and (outcomes) skill use; never duplicated
        assert len(ours) == (3 if event == "PostToolUse" else 1), (event, ours)
        assert len({json.dumps(e, sort_keys=True) for e in ours}) == len(ours)


def test_existing_settings_and_user_hooks_are_preserved(pyweb: Path):
    claude = pyweb / ".claude"
    claude.mkdir()
    user = {"permissions": {"deny": ["Read(./secrets/**)"], "ask": ["Bash(git push:*)"]},
            "hooks": {"PostToolUse": [{"matcher": "Write",
                                       "hooks": [{"type": "command", "command": "echo mine"}]}]},
            "model": "sonnet"}
    (claude / "settings.json").write_text(json.dumps(user))
    _init(pyweb)
    data = json.loads((claude / "settings.json").read_text())
    assert data["permissions"] == user["permissions"], "permissions must never change"
    assert data["model"] == "sonnet"
    commands = [h["command"] for e in data["hooks"]["PostToolUse"] for h in e["hooks"]]
    assert "echo mine" in commands
    assert "bypassPermissions" not in json.dumps(data)
    assert "allow" not in data["permissions"], "repo-ai must not add allow rules"


def test_invalid_settings_json_is_not_overwritten(pyweb: Path):
    claude = pyweb / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{ this is not json")
    proc = run_cli(pyweb, "init", "--agent", "claude")
    assert proc.returncode == 0, proc.stderr
    assert (claude / "settings.json").read_text() == "{ this is not json"
    assert "not valid JSON" in proc.stdout


def test_custom_user_skill_is_never_touched(pyweb: Path):
    skill = pyweb / ".claude" / "skills" / "repo-locate" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: repo-locate\ndescription: my own\n---\n\nmine\n")
    _init(pyweb)
    assert skill.read_text().endswith("mine\n")
    proc = run_cli(pyweb, "uninstall", "--agent", "claude", "-y")
    assert proc.returncode == 0
    assert skill.read_text().endswith("mine\n")


def test_hand_edited_managed_skill_becomes_users(pyweb: Path):
    _init(pyweb)
    skill = pyweb / ".claude" / "skills" / "repo-orient" / "SKILL.md"
    edited = skill.read_text() + "\nMy extra step.\n"
    skill.write_text(edited)
    assert run_cli(pyweb, "update", "-q").returncode == 0
    assert skill.read_text() == edited
    run_cli(pyweb, "uninstall", "-y")
    assert skill.read_text() == edited, "uninstall must keep a hand-edited file"


def test_agents_md_only_repo_keeps_agents_md_loading(pyweb: Path):
    """Claude Code loads AGENTS.md only when CLAUDE.md is absent; the CLAUDE.md
    repo-ai creates must therefore import it."""
    (pyweb / "AGENTS.md").write_text("# Agents\n\nUse pnpm, never npm.\n")
    _init(pyweb)
    text = (pyweb / "CLAUDE.md").read_text()
    assert "\n@AGENTS.md\n" in "\n" + text
    assert (pyweb / "AGENTS.md").read_text() == "# Agents\n\nUse pnpm, never npm.\n"
    run_cli(pyweb, "uninstall", "--agent", "claude", "-y")
    assert not (pyweb / "CLAUDE.md").exists(), "repo-ai created CLAUDE.md; uninstall removes it"
    assert (pyweb / "AGENTS.md").read_text() == "# Agents\n\nUse pnpm, never npm.\n"


def test_both_agents_do_not_duplicate_guidance(pyweb: Path):
    proc = run_cli(pyweb, "init", "--agent", "both", "--smart", "-q")
    assert proc.returncode == 0, proc.stderr
    claude_md = (pyweb / "CLAUDE.md").read_text()
    agents_md = (pyweb / "AGENTS.md").read_text()
    assert "@AGENTS.md" in claude_md
    assert "<!-- BEGIN repo-ai -->" in agents_md
    # Shared facts (commands, knowledge files) live in AGENTS.md only.
    block = claude_md[claude_md.index(BEGIN):]
    assert "Commands (declared" not in block
    assert "Claude Code" in agents_md
    first = snapshot(pyweb)
    run_cli(pyweb, "init", "--agent", "both", "--smart", "-q")
    assert snapshot(pyweb) == first


def test_existing_bob_install_is_preserved_when_adding_claude(pyweb: Path):
    proc = run_cli(pyweb, "init")  # v0.4 behaviour: Bob, .bob/context
    assert proc.returncode == 0, proc.stderr
    bob_before = {k: v for k, v in snapshot(pyweb).items()
                  if k.startswith(".bob/") and not k.startswith(".bob/context/")}
    _init(pyweb)
    after = snapshot(pyweb)
    for key, value in bob_before.items():
        assert after.get(key) == value, f"Bob file changed: {key}"
    assert (pyweb / ".bob" / "context" / "index.db").is_file(), "existing layout must be kept"
    assert not (pyweb / ".repo-ai" / "state").exists()
    status = json.loads(run_cli(pyweb, "status", "--json").stdout)
    assert set(status["agents"]) == {"bob", "claude"}
    assert status["context_dir"] == ".bob/context"


def test_dry_run_and_diff_write_nothing(pyweb: Path):
    before = snapshot(pyweb, skip=(".git",))
    proc = run_cli(pyweb, "init", "--agent", "claude", "--smart", "--diff")
    assert proc.returncode == 0, proc.stderr
    assert "CLAUDE.md" in proc.stdout and "+++ b/.claude/settings.json" in proc.stdout
    assert snapshot(pyweb, skip=(".git",)) == before
    assert not (pyweb / ".repo-ai").exists()


def test_uninstall_dry_run_lists_precise_ownership(pyweb: Path):
    (pyweb / "CLAUDE.md").write_text(HUMAN_CLAUDE)
    _init(pyweb)
    before = snapshot(pyweb, skip=(".git",))
    proc = run_cli(pyweb, "uninstall", "--agent", "claude", "--dry-run")
    assert proc.returncode == 0
    assert snapshot(pyweb, skip=(".git",)) == before
    assert ".claude/skills/repo-locate/SKILL.md" in proc.stdout
    assert "update  CLAUDE.md" in proc.stdout


def test_uninstall_restores_exact_original(pyweb: Path):
    (pyweb / "CLAUDE.md").write_text(HUMAN_CLAUDE)
    (pyweb / ".gitignore").write_text("node_modules/\n*.log\n")
    claude = pyweb / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({"model": "opus"}, indent=2) + "\n")
    before = snapshot(pyweb, skip=(".git",))
    _init(pyweb)
    proc = run_cli(pyweb, "uninstall", "-y")
    assert proc.returncode == 0, proc.stderr
    after = snapshot(pyweb, skip=(".git",))
    assert after == before, sorted(set(after) ^ set(before)) or [
        k for k in after if after[k] != before.get(k)]
    assert not (pyweb / ".repo-ai").exists()


def test_uninstall_removes_every_store_repo_ai_writes_including_prooflab(pyweb: Path):
    """The release-freeze packaging review: after `prove` and `verify --run`, uninstall left
    `.repo-ai/state/prove/` (claim text, scenario bytes, passports) behind, outside any ignore rule."""
    before = snapshot(pyweb, skip=(".git",))
    _init(pyweb)
    state = pyweb / ".repo-ai" / "state"
    for rel, text in {"prove/claims/c.json": "{}", "prove/blobs/" + "a" * 64: "x", "prove/passports/c/1.json": "{}",
                      "runs.jsonl": "{}\n", "sarif/r.sarif": "{}", "verify-other.json": "{}", "gate.json": "{}"}.items():
        (state / rel).parent.mkdir(parents=True, exist_ok=True)
        (state / rel).write_text(text)
    dry = run_cli(pyweb, "uninstall", "--dry-run")
    assert "prove" in dry.stdout, dry.stdout
    proc = run_cli(pyweb, "uninstall", "-y")
    assert proc.returncode == 0, proc.stderr
    assert snapshot(pyweb, skip=(".git",)) == before
    assert not (pyweb / ".repo-ai").exists()


def test_uninstall_keeps_what_it_does_not_recognise(pyweb: Path):
    _init(pyweb)
    mine = pyweb / ".repo-ai" / "state" / "my-notes.txt"
    mine.write_text("not repo-ai's\n")
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert mine.read_text() == "not repo-ai's\n"


def test_uninstall_requires_confirmation_without_tty(pyweb: Path):
    _init(pyweb)
    proc = run_cli(pyweb, "uninstall")
    assert proc.returncode != 0
    assert (pyweb / ".claude" / "settings.json").exists()


def test_local_only_mode(pyweb: Path):
    proc = run_cli(pyweb, "init", "--agent", "claude", "--local-only", "-q")
    assert proc.returncode == 0, proc.stderr
    assert (pyweb / ".claude" / "settings.local.json").is_file()
    assert not (pyweb / ".claude" / "settings.json").exists()
    assert (pyweb / "CLAUDE.local.md").is_file()
    assert not (pyweb / "CLAUDE.md").exists()
    ignore = (pyweb / ".gitignore").read_text()
    for entry in (".repo-ai/context/", ".claude/skills/repo-locate/", "CLAUDE.local.md"):
        assert entry in ignore, entry


def test_custom_out_dir_is_used_everywhere(pyweb: Path):
    (pyweb / ".repo-ai.toml").write_text('out_dir = "docs/ai"\n')
    _init(pyweb)
    assert (pyweb / "docs" / "ai" / "index.db").is_file()
    assert (pyweb / "docs" / "ai" / "ARCHITECTURE.md").is_file()
    assert "docs/ai/" in (pyweb / "CLAUDE.md").read_text()
    ignore = (pyweb / ".gitignore").read_text()
    assert "docs/ai/index.db" in ignore
    assert ".bob/context" not in (pyweb / "CLAUDE.md").read_text()


def test_out_dir_outside_repo_is_refused(pyweb: Path):
    (pyweb / ".repo-ai.toml").write_text('out_dir = "../escape"\n')
    proc = run_cli(pyweb, "init", "--agent", "claude")
    assert proc.returncode != 0
    assert "outside the repository" in proc.stderr
    assert not (pyweb.parent / "escape").exists()


def test_bob_custom_out_dir_hooks_use_it(pyweb: Path):
    (pyweb / ".repo-ai.toml").write_text('out_dir = "ctx"\n')
    assert run_cli(pyweb, "init").returncode == 0
    hook = (pyweb / ".bob" / "hooks" / "user-prompt.sh").read_text()
    assert "ctx/index.db" in hook and ".bob/context" not in hook


def test_no_git_repository_still_works(tmp_path: Path):
    repo = make_repo(tmp_path, "goservice", git=False)
    proc = run_cli(repo, "init", "--agent", "claude", "-q")
    assert proc.returncode == 0, proc.stderr
    out = run_cli(repo, "context", "ReserveItem returns 409 when stock is insufficient",
                  "--format", "paths")
    assert "internal/api/handlers.go" in out.stdout.splitlines()[:3]


def test_doctor_reports_claude_wiring(pyweb: Path):
    _init(pyweb)
    proc = run_cli(pyweb, "doctor", "--agent", "claude", "--json")
    checks = {c["label"]: c for c in json.loads(proc.stdout)}
    assert checks["claude: CLAUDE.md managed block"]["status"] == "ok"
    assert checks["claude: UserPromptSubmit hook"]["status"] == "ok"
    assert checks["claude: skills"]["status"] == "ok"
    assert checks["index"]["status"] == "ok"


@pytest.mark.parametrize("agent", ["claude", "bob"])
def test_uninstall_single_agent_keeps_other(pyweb: Path, agent: str):
    assert run_cli(pyweb, "init", "--agent", "both", "-q").returncode == 0
    assert run_cli(pyweb, "uninstall", "--agent", agent, "-y").returncode == 0
    other = "bob" if agent == "claude" else "claude"
    status = json.loads(run_cli(pyweb, "status", "--json").stdout)
    assert status["agents"] == [other]
    if agent == "claude":
        assert not (pyweb / ".claude" / "skills" / "repo-locate").exists()
        assert (pyweb / ".bob" / "hooks" / "user-prompt.sh").is_file()
    else:
        assert not (pyweb / ".bob" / "hooks").exists()
        assert (pyweb / ".claude" / "skills" / "repo-locate" / "SKILL.md").is_file()


def test_plugin_bundle_is_current_and_valid():
    import shutil
    import subprocess
    import sys
    root = Path(__file__).resolve().parent.parent
    check = subprocess.run([sys.executable, str(root / "scripts" / "build_plugin.py"), "--check"],
                           capture_output=True, text=True, encoding="utf-8", check=False)
    assert check.returncode == 0, check.stdout
    from repo_ai.skillcheck import validate_skill_file
    for skill in (root / "integrations" / "claude-plugin" / "skills").glob("*/SKILL.md"):
        assert validate_skill_file(skill).ok, skill
    if shutil.which("claude"):
        for target in (root / "integrations" / "claude-plugin", root):
            proc = subprocess.run(["claude", "plugin", "validate", str(target)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
            assert proc.returncode == 0 and "Validation passed" in proc.stdout, proc.stdout


def test_generated_claude_dir_passes_claude_validation(pyweb: Path):
    import shutil
    import subprocess
    if not shutil.which("claude"):
        pytest.skip("Claude Code CLI not installed")
    _init(pyweb)
    proc = subprocess.run(["claude", "plugin", "validate", str(pyweb / ".claude")],
                          capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert proc.returncode == 0 and "Validation passed" in proc.stdout, proc.stdout
