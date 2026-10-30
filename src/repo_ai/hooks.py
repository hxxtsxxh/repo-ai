"""Claude Code hook runtime: `repo-ai hook claude <event>`.

Contract (Claude Code 2.1.x):

  * stdin is one JSON object (`hook_event_name`, `session_id`, `cwd`, and
    event fields such as `prompt`, `tool_name`, `tool_input`, `source`,
    `stop_hook_active`);
  * on exit 0, SessionStart / UserPromptSubmit may return
    `{"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}`
    (capped by Claude Code at 10,000 characters);
  * exit 2 would *block* the prompt or the stop, so this module never returns 2.

Fail-open everywhere: malformed input, a missing index, a locked database, a
slow query (hard alarm) — all produce zero bytes and exit 0. Nothing here
prints prompt text, file content or secrets to stdout or logs.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MAX_STDIN = 2_000_000
HARD_TIMEOUT_S = 6
CONTEXT_CHAR_CAP = 9_000  # below Claude Code's 10k additionalContext cap


class _Timeout(BaseException):  # not swallowed by `except Exception` inside handlers
    pass


def _alarm(_signum, _frame):  # pragma: no cover - timing dependent
    raise _Timeout()


def _debug(msg: str) -> None:
    if os.environ.get("REPO_AI_HOOK_DEBUG"):
        print(f"repo-ai hook: {msg}", file=sys.stderr)


def _payload(text: str) -> dict[str, Any]:
    if not text or len(text) > MAX_STDIN:
        return {}
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def project_root(payload: dict[str, Any]) -> Path | None:
    """CLAUDE_PROJECT_DIR (the project root) wins over the session cwd."""
    for candidate in (os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd"), os.getcwd()):
        if not candidate or not isinstance(candidate, str):
            continue
        try:
            path = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if path.is_dir():
            return path
    return None


def _workspace(root: Path):
    from .config import load_config
    from .paths import detect_kind, resolve_layout

    cfg = load_config(root)
    layout = resolve_layout(root, cfg, prefer=detect_kind(root) or "standard")
    if not layout.index_path.is_file():
        # Session may have started in a subdirectory of the repository.
        from .gitinfo import find_repo_root
        top = find_repo_root(root)
        if top != root:
            cfg = load_config(top)
            layout = resolve_layout(top, cfg, prefer=detect_kind(top) or "standard")
            root = top
    if not layout.index_path.is_file():
        return None
    from .optimize import apply_tuning
    return root, apply_tuning(cfg, layout), layout


def _context_out(event: str, text: str) -> str:
    if not text:
        return ""
    return json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                              "additionalContext": text[:CONTEXT_CHAR_CAP]}})


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------
def on_prompt(payload: dict[str, Any]) -> str:
    from .index import open_index
    from .retrieval import adaptive_cut, cached_search, is_trivial_prompt, render_claude

    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return ""
    prompt = prompt.strip()
    if not prompt or prompt.startswith(("/", "!", "#")):
        return ""  # slash commands, bash mode, memory shortcuts
    root = project_root(payload)
    ws = _workspace(root) if root else None
    if ws is None:
        return ""
    root, cfg, layout = ws
    from . import flight
    started = time.monotonic()
    trace: dict[str, Any] = {"event": "prompt", "prompt_sha": flight.prompt_fingerprint(prompt),
                             "prompt_chars": len(prompt)}
    if is_trivial_prompt(prompt, cfg.hook_min_prompt_chars):
        flight.record(layout, cfg, {**trace, "decision": "omitted", "reason": "trivial prompt"})
        return ""
    from . import episodes
    session = str(payload.get("session_id", ""))
    stale = layout.dirty_path.exists()
    index = open_index(layout.state_dir, busy_timeout_ms=1500)
    try:
        result = cached_search(index, prompt[:4000], max_files=max(cfg.hook_max_files, 1) * 2,
                               include_tests=True, use_cache=cfg.query_cache,
                               prior=episodes.load_prior(layout))
        trace.update(confidence=result.confidence, intents=result.query.intents,
                     cache_hit=result.cached, index_age_s=_index_age(index.get_meta("generated_at")),
                     candidates=[{"path": h.path, "score": round(h.score, 2)}
                                 for h in result.hits[:10]])
        if result.confidence not in {"high", "medium"}:
            _debug(f"confidence {result.confidence}: nothing injected")
            episodes.note_prompt(layout, cfg, session, result.query.intents,
                                 [(h.path, h.score) for h in result.hits], [],
                                 result.confidence, stale)
            flight.record(layout, cfg, {**trace, "decision": "omitted",
                                        "reason": f"confidence {result.confidence}",
                                        "elapsed_ms": _ms(started)})
            return ""
        result.hits = adaptive_cut(result.hits, cfg.hook_max_files)
        verify = _focused_test(index, layout, result)
    finally:
        index.close()
    if cfg.learning_signals in ("known-commands", "outcomes"):
        from .signals import record
        record(layout, "intent", ",".join(result.query.intents),
               str(payload.get("session_id", "")))
    text = render_claude(result, cfg.hook_budget_tokens, verify,
                         _quarantined(layout), CONTEXT_CHAR_CAP)
    episodes.note_prompt(layout, cfg, session, result.query.intents,
                         [(h.path, h.score) for h in result.hits],
                         [h.path for h in result.hits] if text else [], result.confidence, stale)
    flight.record(layout, cfg, {**trace, "decision": "injected" if text else "omitted",
                                "reason": "" if text else "nothing fit the budget",
                                "injected": [h.path for h in result.hits] if text else [],
                                "tokens_est": (len(text) + 3) // 4, "elapsed_ms": _ms(started)})
    return _context_out("UserPromptSubmit", text)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _index_age(generated_at: str | None) -> int | None:
    if not generated_at:
        return None
    from datetime import datetime, timezone
    try:
        stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))


def _quarantined(layout) -> frozenset[str]:
    try:
        facts = json.loads((layout.context_dir / "facts.json").read_text("utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return frozenset(facts.get("quarantined", []))


def _focused_test(index, layout, result) -> str:
    from .impact import _focused_for
    try:
        facts = json.loads((layout.context_dir / "facts.json").read_text("utf-8"))
    except (OSError, ValueError):
        return ""
    suites = sorted(facts.get("test_suites", []), key=lambda s: -len(s.get("root", "")))
    tests = [h.path for h in result.hits if h.role == "test"]
    if not tests:
        for hit in result.hits[:3]:
            tests += [r["test_path"] for r in index.tests_for(hit.path)][:1]
    for test in tests[:1]:
        suite = next((s for s in suites if s.get("root") in {"", "."}
                      or test.startswith(s.get("root", "").rstrip("/") + "/")), None)
        if suite:
            return _focused_for(suite.get("framework", ""), suite.get("command", ""), test)
    return ""


def on_session_start(payload: dict[str, Any]) -> str:
    from .gitinfo import changed_since, current_head, is_git_repo
    from .index import open_index

    root = project_root(payload)
    ws = _workspace(root) if root else None
    if ws is None:
        return ""
    root, cfg, layout = ws
    from .scanner import real_drift
    index = open_index(layout.state_dir, busy_timeout_ms=1500)
    try:
        files = index.get_meta("indexed_files") or "?"
        indexed_head = index.get_meta("git_head")
        drift: list[str] = []
        if indexed_head and is_git_repo(root):
            prefix = layout.context_rel + "/"
            drift = real_drift(root, index, [p for p in changed_since(root, indexed_head)
                                             if not p.startswith((prefix, ".repo-ai/", ".claude/", ".bob/"))])
        incomplete = index.get_meta("needs_reanalysis") == "1"  # an update was interrupted
    finally:
        index.close()
    head = current_head(root) if is_git_repo(root) else ""
    lines = [f"repo-ai: {files} files indexed" + (f" at {indexed_head}" if indexed_head else "") + "."]
    if drift or incomplete or layout.dirty_path.exists():
        n = len(drift)
        lines.append((f"{n} file(s) changed since indexing; " if n else "")
                     + "a background refresh was started.")
        spawn_refresh(root, force=True)
    elif head and indexed_head and head != indexed_head:
        lines.append("HEAD moved since indexing; a background refresh was started.")
        spawn_refresh(root, force=True)
    lines.append("Relevant prompts get a ranked file shortlist automatically; "
                 "/repo-locate, /repo-impact and /repo-verify go deeper.")
    return _context_out("SessionStart", " ".join(lines))


def on_post_edit(payload: dict[str, Any]) -> str:
    root = project_root(payload)
    ws = _workspace(root) if root else None
    if ws is None:
        return ""
    root, cfg, layout = ws
    raw_input = payload.get("tool_input")
    tool_input: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    rel = ""
    if isinstance(raw, str) and raw:
        try:
            path = Path(raw).expanduser()
            path = (path if path.is_absolute() else root / path).resolve()
            rel = path.relative_to(root.resolve()).as_posix()
        except (OSError, ValueError, RuntimeError):
            return ""  # outside the repository: not ours to index
        if rel in {"", "."} or path.is_dir():
            return ""  # not a file edit
    mark_dirty(layout, rel)
    if rel:
        from . import episodes
        episodes.note_edit(layout, cfg, str(payload.get("session_id", "")), rel)
    if rel and cfg.learning_signals in ("known-commands", "outcomes"):
        _record_generated_edit(layout, rel, str(payload.get("session_id", "")))
    return ""


def _record_generated_edit(layout, rel: str, session: str) -> None:
    from .index import open_index
    from .signals import record
    try:
        index = open_index(layout.state_dir, busy_timeout_ms=500)
        try:
            row = index.get_file(rel)
        finally:
            index.close()
    except Exception:
        return
    if row is not None and row["role"] == "generated":
        parent = rel.rsplit("/", 1)[0] + "/" if "/" in rel else rel
        record(layout, "edit-generated", parent, session)


def on_post_bash(payload: dict[str, Any], failed: bool) -> str:
    root = project_root(payload)
    ws = _workspace(root) if root else None
    if ws is None:
        return ""
    root, cfg, layout = ws
    if cfg.learning_signals not in ("known-commands", "outcomes"):
        return ""
    raw_input = payload.get("tool_input")
    tool_input: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        return ""
    try:
        facts = json.loads((layout.context_dir / "facts.json").read_text("utf-8"))
    except (OSError, ValueError):
        return ""
    from .signals import match_known_command, record
    match = match_known_command(command, facts.get("commands", {}))
    if match:
        record(layout, "cmd-fail" if failed else "cmd", match[1],
               str(payload.get("session_id", "")), kind=match[0])
        from . import episodes
        episodes.note_command(layout, cfg, str(payload.get("session_id", "")), match[0],
                              match[1], not failed)
    return ""


def on_stop(payload: dict[str, Any]) -> str:
    if payload.get("stop_hook_active"):
        return ""  # never participate in a stop-hook loop
    root = project_root(payload)
    ws = _workspace(root) if root else None
    if ws is None:
        return ""
    root, cfg, layout = ws
    from . import episodes
    episodes.close(layout, cfg, str(payload.get("session_id", "")))
    # `.dirty.processing` without a refresh running: a refresh was killed after claiming the
    # dirty marker; it must run again (it used to wait for the next session start)
    if layout.dirty_path.exists() or layout.dirty_path.with_name(".dirty.processing").exists():
        spawn_refresh(root)
    if cfg.verify_gate:  # opt-in completion gate: silent unless this change is unverified
        from .verify.gate import decision
        return decision(root, layout, payload, mode=cfg.verify_gate_mode,
                        max_blocks=cfg.verify_gate_max_blocks)
    return ""


# --------------------------------------------------------------------------
# dirty marker + debounced background refresh
# --------------------------------------------------------------------------
def mark_dirty(layout, rel: str = "") -> None:
    try:
        layout.state_dir.mkdir(parents=True, exist_ok=True)
        line = (rel.replace("\n", " ")[:500] if rel else "*") + "\n"
        fd = os.open(str(layout.dirty_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND
                     | getattr(os, "O_NOFOLLOW", 0), 0o644)
        try:
            os.write(fd, line.encode("utf-8", errors="replace"))
        finally:
            os.close(fd)
    except OSError:
        pass


def spawn_refresh(root: Path, force: bool = False) -> bool:
    """Start `repo-ai refresh` detached. Returns False if skipped."""
    if os.environ.get("REPO_AI_NO_BACKGROUND"):
        return False
    from .config import load_config
    from .locks import is_locked
    from .paths import detect_kind, resolve_layout

    cfg = load_config(root)
    layout = resolve_layout(root, cfg, prefer=detect_kind(root) or "standard")
    if is_locked(layout.lock_path):
        return False  # an update is already running: do not stack another
    try:
        last = layout.stamp_path.stat().st_mtime
    except OSError:
        last = 0.0
    if not force and time.time() - last < cfg.refresh_debounce_seconds:
        return False
    from .fsutil import self_argv
    args = self_argv("refresh", "-C", str(root), "--quiet")
    if force:
        args.append("--force")
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                              "stderr": subprocess.DEVNULL, "cwd": str(root),
                              "env": {**os.environ, "REPO_AI_IN_HOOK": "1"}}
    if os.name == "nt":  # pragma: no cover
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(args, **kwargs)  # noqa: S603 - fixed argv, no shell
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# dispatcher
# --------------------------------------------------------------------------
def on_post_skill(payload: dict[str, Any]) -> str:
    import re as _re
    root = project_root(payload)
    ws = _workspace(root) if root else None
    if ws is None:
        return ""
    root, cfg, layout = ws
    raw_input = payload.get("tool_input")
    tool_input: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    name = next((v for k in ("skill", "name", "command") if isinstance(v := tool_input.get(k), str)), "")
    name = name.strip().lstrip("/").split()[0] if name.strip() else ""
    if not _re.fullmatch(r"[a-z0-9][a-z0-9:_-]{0,63}", name):
        return ""  # only well-formed skill names; never arguments
    from . import episodes
    from .skills import SkillState
    version = int(SkillState.load(layout).entries.get(name, {}).get("version", 0) or 0)
    episodes.note_skill(layout, cfg, str(payload.get("session_id", "")), name, version)
    return ""


HANDLERS = {
    "post-skill": on_post_skill,
    "prompt": on_prompt,
    "session-start": on_session_start,
    "post-edit": on_post_edit,
    "stop": on_stop,
    "post-bash": lambda p: on_post_bash(p, failed=False),
    "post-bash-failure": lambda p: on_post_bash(p, failed=True),
}


def run(event: str, stdin_text: str) -> str:
    handler = HANDLERS.get(event)
    if handler is None:
        return ""
    payload = _payload(stdin_text)
    use_alarm = hasattr(signal, "SIGALRM")
    if use_alarm:
        previous = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(HARD_TIMEOUT_S)
    try:
        return handler(payload) or ""
    except _Timeout:
        _debug(f"{event}: exceeded {HARD_TIMEOUT_S}s; nothing injected")
        return ""
    except Exception as exc:  # fail open, always
        _debug(f"{event}: {type(exc).__name__}: {exc}")
        return ""
    finally:
        if use_alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
