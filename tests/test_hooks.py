"""Claude Code hook contract: valid JSON, fail-open, bounded, no recursion."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import cli_env, run_cli, run_hook


@pytest.fixture
def wired(pyweb: Path) -> Path:
    proc = run_cli(pyweb, "init", "--agent", "claude", "--smart", "-q")
    assert proc.returncode == 0, proc.stderr
    return pyweb


def _context(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0
    if not proc.stdout.strip():
        return ""
    data = json.loads(proc.stdout)
    assert data["hookSpecificOutput"]["hookEventName"] in {"UserPromptSubmit", "SessionStart"}
    return data["hookSpecificOutput"]["additionalContext"]


def test_relevant_prompt_injects_ranked_shortlist(wired: Path):
    proc = run_hook(wired, "prompt", {"hook_event_name": "UserPromptSubmit", "session_id": "s",
                                      "cwd": str(wired),
                                      "prompt": "fix the login validation bug for valid emails"})
    text = _context(proc)
    assert text.startswith("<repo-ai-context")
    lines = [ln for ln in text.splitlines() if ln[:2].rstrip(".").isdigit()]
    assert "app/auth/login.py" in lines[0]
    assert any("tests/test_login.py" in ln for ln in lines[:5])
    assert "Verify with: `pytest tests/test_login.py`" in text


@pytest.mark.parametrize("prompt", [
    "write me a haiku about autumn leaves",
    "thanks, that looks great, please continue",
    "yes",
    "/repo-orient",
    "!git status",
    "",
])
def test_irrelevant_or_trivial_prompts_inject_nothing(wired: Path, prompt: str):
    proc = run_hook(wired, "prompt", {"prompt": prompt})
    assert proc.returncode == 0
    assert proc.stdout == ""


@pytest.mark.parametrize("payload", ["", "not json", "[1,2,3]", '{"prompt": 42}',
                                     '{"prompt": null}', "{" * 5000])
def test_malformed_stdin_fails_open(wired: Path, payload: str):
    proc = run_hook(wired, "prompt", payload)
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_hard_token_budget(wired: Path):
    (wired / ".repo-ai" / "config.toml").write_text(
        (wired / ".repo-ai" / "config.toml").read_text() + "\nhook_budget_tokens = 80\n")
    proc = run_hook(wired, "prompt", {"prompt": "fix the login validation bug for valid emails"})
    text = _context(proc)
    assert len(text) // 4 <= 80


def test_missing_index_is_silent(pyweb: Path):
    proc = run_hook(pyweb, "prompt", {"prompt": "fix the login validation bug for valid emails"})
    assert proc.returncode == 0 and proc.stdout == ""


def test_unknown_event_and_bad_args_never_exit_2(wired: Path):
    for args in (["hook", "claude", "nonsense"], ["hook", "bob", "prompt"], ["hook"]):
        proc = subprocess.run([sys.executable, "-m", "repo_ai", *args], input="{}", text=True, encoding="utf-8",
                              capture_output=True, env=cli_env(), cwd=wired, check=False)
        assert proc.returncode == 0, (args, proc.returncode, proc.stderr)


def test_dispatcher_script_is_silent_without_repo_ai(wired: Path):
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(wired)}
    proc = subprocess.run(["sh", str(wired / ".claude" / "hooks" / "repo-ai.sh"), "prompt"],
                          input='{"prompt": "fix login validation"}', text=True, encoding="utf-8",
                          capture_output=True, env=env, check=False)
    assert proc.returncode == 0 and proc.stdout == ""


def test_session_start_is_brief(wired: Path):
    text = _context(run_hook(wired, "session-start", {"hook_event_name": "SessionStart",
                                                       "source": "startup"}))
    assert text.startswith("repo-ai:")
    assert len(text) // 4 < 200


def test_post_edit_marks_dirty_only_inside_repo(wired: Path):
    dirty = wired / ".repo-ai" / "state" / ".dirty"
    run_hook(wired, "post-edit", {"tool_name": "Edit", "tool_input": {"file_path": "/etc/hosts"}})
    assert not dirty.exists()
    run_hook(wired, "post-edit", {"tool_name": "Write",
                                  "tool_input": {"file_path": str(wired / "app" / "auth" / "login.py")}})
    assert dirty.read_text().strip() == "app/auth/login.py"
    run_hook(wired, "post-edit", {"tool_name": "Edit",
                                  "tool_input": {"file_path": "../../outside.py"}})
    assert dirty.read_text().strip() == "app/auth/login.py"


def test_stop_hook_never_recurses(wired: Path):
    proc = run_hook(wired, "stop", {"stop_hook_active": True})
    assert proc.returncode == 0 and proc.stdout == ""


def test_refresh_is_lock_protected_and_debounced(wired: Path):
    from repo_ai.locks import file_lock
    lock = wired / ".repo-ai" / "state" / "update.lock"
    (wired / "app" / "billing" / "fees.py").write_text("def late_fee() -> int:\n    return 5\n")
    (wired / ".repo-ai" / "state" / ".dirty").write_text("app/billing/fees.py\n")
    with file_lock(lock, timeout=1) as held:
        assert held
        started = time.monotonic()
        proc = run_cli(wired, "refresh", "--force")
        assert proc.returncode == 0
        assert time.monotonic() - started < 10, "refresh must not wait on the lock"
    assert (wired / ".repo-ai" / "state" / ".dirty").exists(), "skipped refresh keeps the marker"
    proc = run_cli(wired, "refresh", "--force")
    assert proc.returncode == 0
    assert not (wired / ".repo-ai" / "state" / ".dirty").exists()
    out = run_cli(wired, "symbol", "late_fee")
    assert "app/billing/fees.py" in out.stdout


def test_concurrent_refreshes_do_not_corrupt_index(wired: Path):
    (wired / "app" / "billing" / "tax.py").write_text("def vat(x: int) -> int:\n    return x\n")
    (wired / ".repo-ai" / "state" / ".dirty").write_text("app/billing/tax.py\n")
    procs = [subprocess.Popen([sys.executable, "-m", "repo_ai", "refresh", "--force", "-C", str(wired)],
                              env=cli_env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
             for _ in range(4)]
    for p in procs:
        assert p.wait(timeout=120) == 0
    import sqlite3
    conn = sqlite3.connect(wired / ".repo-ai" / "state" / "index.db")
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()
    assert "app/billing/tax.py" in run_cli(wired, "symbol", "vat").stdout


def test_hook_latency_is_reasonable(wired: Path):
    payload = {"prompt": "stripe charges fail with zero amount when creating a booking"}
    run_hook(wired, "prompt", payload)  # warm caches
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        run_hook(wired, "prompt", payload)
        timings.append(time.perf_counter() - started)
    # Generous bound for slow CI machines; benchmarks/run.py records real numbers.
    assert min(timings) < 2.0, timings


def test_known_command_signals_store_no_free_text(wired: Path):
    run_hook(wired, "post-bash", {"tool_name": "Bash", "session_id": "abc",
                                  "tool_input": {"command": "make test"}})
    run_hook(wired, "post-bash", {"tool_name": "Bash", "session_id": "abc",
                                  "tool_input": {"command": "curl -H 'Authorization: secret' x"}})
    run_hook(wired, "prompt", {"session_id": "abc",
                               "prompt": "fix the login validation bug for valid emails"})
    signals = (wired / ".repo-ai" / "state" / "signals.jsonl").read_text()
    assert "make test" in signals
    assert "curl" not in signals and "secret" not in signals
    assert "login" not in signals, "prompt text must never be stored"
    assert "abc" not in signals, "session ids are hashed"
    proc = run_cli(wired, "learn", "--forget-signals")
    assert proc.returncode == 0
    assert not (wired / ".repo-ai" / "state" / "signals.jsonl").exists()


def test_signals_off_by_default_without_smart(pyweb: Path):
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    settings = json.loads((pyweb / ".claude" / "settings.json").read_text())
    assert "PostToolUseFailure" not in settings["hooks"]
    assert all("post-bash" not in json.dumps(e) for e in settings["hooks"]["PostToolUse"])
    run_hook(pyweb, "post-bash", {"tool_input": {"command": "make test"}})
    assert not (pyweb / ".repo-ai" / "state" / "signals.jsonl").exists()


def test_hook_works_from_subdirectory_cwd(wired: Path):
    env = cli_env()
    env.pop("CLAUDE_PROJECT_DIR", None)
    proc = subprocess.run([sys.executable, "-m", "repo_ai", "hook", "claude", "prompt"],
                          input=json.dumps({"prompt": "fix the login validation bug for valid emails",
                                            "cwd": str(wired / "app" / "auth")}),
                          text=True, encoding="utf-8", capture_output=True, env=env, cwd=wired / "app" / "auth",
                          check=False)
    assert "app/auth/login.py" in _context(proc)


def test_flight_recorder_is_off_by_default_and_never_stores_prompts(pyweb: Path):
    from conftest import run_cli, run_hook
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    secret_prompt = "fix the login validation bug where users with a valid email are rejected"
    run_hook(pyweb, "prompt", {"prompt": secret_prompt})
    assert not (pyweb / ".repo-ai" / "state" / "flight.jsonl").exists()
    assert "flight recorder is off" in run_cli(pyweb, "debug").stdout

    (pyweb / ".repo-ai" / "config.toml").write_text(
        (pyweb / ".repo-ai" / "config.toml").read_text() + "\nflight_recorder = true\n")
    run_hook(pyweb, "prompt", {"prompt": secret_prompt})
    run_hook(pyweb, "prompt", {"prompt": "write a haiku about autumn leaves falling slowly"})
    log = (pyweb / ".repo-ai" / "state" / "flight.jsonl").read_text()
    assert "valid email" not in log and "haiku" not in log
    rows = [json.loads(line) for line in log.splitlines()]
    assert rows[0]["decision"] == "injected" and rows[0]["injected"][0] == "app/auth/login.py"
    assert rows[1]["decision"] == "omitted" and rows[1]["reason"].startswith("confidence")
    out = run_cli(pyweb, "debug", "last", "-n", "2").stdout
    assert "injected" in out and "omitted" in out and "+" in out
    assert run_cli(pyweb, "debug", "purge").returncode == 0
    assert not (pyweb / ".repo-ai" / "state" / "flight.jsonl").exists()
