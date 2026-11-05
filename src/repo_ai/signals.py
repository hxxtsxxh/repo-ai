"""Opt-in local workflow signals (`learning_signals = "known-commands"`).

What is recorded, and nothing else:

  * which of the repository's *own* known commands (from manifests/docs) ran,
    and whether Claude Code reported the tool call as failed;
  * the task classes of prompts (e.g. "bug", "auth") — never the prompt text;
  * edits to files repo-ai classifies as generated (directory only).

Session ids are hashed. Unknown commands are dropped, not stored. The file
lives in the gitignored state directory, is capped in size, and
`repo-ai learn --forget-signals` deletes it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .paths import Layout

MAX_LINES = 2000
KEEP_LINES = 1000


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(("repo-ai:" + (session_id or "")).encode()).hexdigest()[:10]


def normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def match_known_command(command: str, known: dict[str, list[str]]) -> tuple[str, str] | None:
    """Return (kind, known command) when `command` runs one of the repo's
    declared commands (exactly, or with extra arguments)."""
    norm = normalize_command(command)
    if not norm or len(norm) > 400 or "\n" in command:
        return None
    best: tuple[str, str] | None = None
    for kind in sorted(known):
        for candidate in known[kind]:
            cand = normalize_command(candidate)
            if norm == cand or norm.startswith(cand + " "):
                if best is None or len(cand) > len(best[1]):
                    best = (kind, cand)
    return best


def record(layout: Layout, event: str, key: str, session_id: str = "", **extra: Any) -> None:
    path = layout.signals_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": int(time.time()), "event": event, "key": key,
                 "session": _session_hash(session_id), **extra}
        line = json.dumps(entry, sort_keys=True) + "\n"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        _maybe_trim(path)
    except OSError:
        pass  # signals are best-effort and must never break a hook


def _maybe_trim(path: Path) -> None:
    try:
        if path.stat().st_size < 160_000:
            return
        lines = path.read_text("utf-8", errors="replace").splitlines()
        if len(lines) > MAX_LINES:
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines[-KEEP_LINES:]) + "\n", encoding="utf-8")
            os.replace(tmp, path)
    except OSError:
        pass


def read_signals(layout: Layout, max_age_days: int = 60) -> list[dict[str, Any]]:
    path = layout.signals_path
    try:
        text = path.read_text("utf-8", errors="replace")
    except OSError:
        return []
    cutoff = time.time() - max_age_days * 86400
    out = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("ts", 0) >= cutoff:
            out.append(item)
    return out


def forget(layout: Layout) -> bool:
    try:
        layout.signals_path.unlink()
        return True
    except FileNotFoundError:
        return False


def command_sessions(signals: list[dict[str, Any]]) -> dict[str, set[str]]:
    """known command -> set of (hashed) sessions it ran in."""
    out: dict[str, set[str]] = {}
    for item in signals:
        if item.get("event") in {"cmd", "cmd-fail"}:
            out.setdefault(item.get("key", ""), set()).add(item.get("session", ""))
    return out


def command_sequences(signals: list[dict[str, Any]]) -> dict[tuple[str, ...], set[str]]:
    """Ordered distinct known-command sequences per session -> sessions."""
    per_session: dict[str, list[str]] = {}
    for item in sorted(signals, key=lambda s: s.get("ts", 0)):
        if item.get("event") != "cmd":
            continue
        seq = per_session.setdefault(item.get("session", ""), [])
        key = item.get("key", "")
        if key and (not seq or seq[-1] != key):
            seq.append(key)
    out: dict[tuple[str, ...], set[str]] = {}
    for session, seq in per_session.items():
        for i in range(len(seq) - 1):
            pair = tuple(seq[i:i + 2])
            if len(set(pair)) == 2:
                out.setdefault(pair, set()).add(session)
    return out
